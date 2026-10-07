"""Independent per-stage reviews with immutable input revisions and saved outputs."""
import re
import tempfile
import time
import uuid
from pathlib import Path
from ctrl_assistant import OCR_PROMPT, ANSWER_PROMPT, ROOT, parse_route, route_prompt


class Reviews:
    def __init__(self, owner):
        self.owner = owner
        self.runs = {}

    def seed(self, session):
        versions = session.setdefault('versions', {'ocr': [], 'analysis': [], 'answer': []})
        if session['original'] and not versions['ocr']:
            value = {'id':'base', 'model':session.get('assigned') or 'input',
                     'text':session['original'], 'based_on':None, 'created_at':session.get('created_at',time.time())}
            versions['ocr'].append(value)
        session.setdefault('original_revision', 'base')
        seeded = session.setdefault('version_seeded', [])
        # Restored completed tasks have no live receipts, but their results are usable.
        for stage, field in [('analysis','route'), ('answer','answer')]:
            for name, model in session['models'].items():
                key = 'base-'+name
                if model.get(field) and stage+name not in seeded:
                    versions[stage].append({'id':key, 'model':name, field:model[field],
                        'based_on':'base', 'created_at':session.get('created_at',time.time())})
                    seeded.append(stage+name)
        return versions

    def record(self, job_id, name, fields):
        job = self.owner.jobs.items[job_id]
        session = self.owner.sessions.get(job.get('session'))
        if not session or job.get('kind','').startswith('ctrl-review'):
            return
        versions = self.seed(session)
        for stage, field in [('analysis','route'), ('answer','answer')]:
            if not fields.get(field):
                continue
            key = job_id+':'+name+':'+stage
            # Replace the initial seed for this provider once with its live result.
            versions[stage][:] = [v for v in versions[stage] if v['id'] != 'base-'+name]
            if not any(v['id'] == key for v in versions[stage]):
                versions[stage].append({'id':key,'model':name,field:fields[field],
                    'based_on':job.get('based_on',session['original_revision']), 'created_at':time.time(),
                    'actual_model':fields.get('actual_model'),'requested_model':fields.get('requested_model')})
                versions[stage][:] = versions[stage][-20:]

    def submit(self, data):
        owner = self.owner
        with owner.intake_lock:
            session_id, stage = data.get('session'), data.get('stage')
            session = owner.sessions.get(session_id)
            if not session or stage not in ('ocr','analysis','answer'):
                raise ValueError('请选择有效题目和复核环节')
            if stage == 'ocr' and not session.get('image'):
                raise ValueError('识题复核需要原截图；文字题无需 OCR')
            if stage != 'ocr' and not session['original']:
                raise ValueError('请先识别原题')
            choice = data.get('model')
            if not isinstance(choice, str):
                raise ValueError('请选择复核模型')
            name, _, model_id = choice.partition(':')
            if name not in owner.providers:
                raise ValueError('未知复核模型')
            provider = owner.providers[name]
            config = None
            if getattr(provider,'is_api',False):
                with provider.lock:
                    config = dict(provider.config)
                if not config.get('api_key'):
                    raise ValueError('请先配置该模型的 API Key')
                if model_id:
                    config = provider._validated({**config,'model':model_id})
                if name == 'intern' and stage == 'ocr':
                    from intern_api import VISION_MODELS
                    if config['model'] not in VISION_MODELS:
                        raise ValueError('OCR 复核请选择支持图片的模型')
            elif model_id:
                raise ValueError('网页模型不能指定 API 模型 ID')
            with owner.jobs.lock:
                self.seed(session)
            for job_id, run in self.runs.items():
                if (run['session'] == session_id and run['stage'] == stage and run['choice'] == choice
                    and run['based_on'] == session['original_revision']
                    and owner.jobs.items.get(job_id,{}).get('state') == 'running'):
                    return {'id':job_id,'session':session_id,'resumed':True}
            job_id = owner._reserve('ctrl-review-'+stage, session_id, [name])
            run = {'session':session_id,'stage':stage,'choice':choice,'name':name,'config':config,
                'original':session['original'],'image':session.get('image'),
                'suffix':session.get('image_suffix'), 'based_on':session['original_revision'],
                'context':{}, 'thinking':bool(data.get('thinking',False))}
            self.runs[job_id] = run
            owner._submit_model(job_id,name,self.execute,job_id,False,priority=0)
            return {'id':job_id,'session':session_id}

    def execute(self, job_id, previous_id, restart, name):
        from ctrl_multi import CtrlProgress
        owner = self.owner
        run = self.runs[previous_id]
        self.runs[job_id] = run
        provider, path = owner.providers[name], None
        stage = run['stage']
        labels = {'ocr':'识题','analysis':'检索建议','answer':'答案'}
        owner._mark(job_id,name,stage=labels[stage]+'复核中')
        if restart:
            run.pop('text',None)
            old = run['context'].pop('receipt',None)
            if old:
                try:
                    provider.close_saved_response(old)
                except Exception:
                    pass
        text = run.get('text')
        if not text and not restart and run['context'].get('receipt'):
            text = owner._read_saved_reply(name,run['context'])
        try:
            if not text:
                image = run['image'] if stage == 'ocr' else None
                if stage == 'answer' and re.search(r'如图|下图|图中|下表|表中|图示|公式|坐标|曲线',run['original']):
                    image = run['image']
                    if name == 'intern':
                        from intern_api import VISION_MODELS
                        if run['config']['model'] not in VISION_MODELS:
                            image = None
                if image:
                    folder = ROOT/'.runtime/uploads'; folder.mkdir(parents=True,exist_ok=True)
                    with tempfile.NamedTemporaryFile(dir=folder,suffix=run['suffix'],delete=False) as file:
                        file.write(image); path = Path(file.name)
                prompt = OCR_PROMPT if stage == 'ocr' else ('原题：\n'+run['original']+'\n'+
                    (route_prompt(run['original'],False) if stage == 'analysis' else ANSWER_PROMPT))
                context = run['context']
                context['guarded'] = hasattr(provider,'_transport')
                progress = CtrlProgress(owner,job_id,name,context)
                progress.api_config = run['config']
                progress.api_options = {'thinking':run['thinking'],'effort':'low'}
                result = provider.generate_with_progress(progress.prompt(prompt),path,progress)
                context['receipt'] = result.get('cleanup_receipt')
                if context['guarded']:
                    progress.confirm_result(result)
                if result.get('status') != 'completed' or not result.get('text','').strip():
                    raise RuntimeError(result.get('detail') or '复核未返回完整内容')
                text = result['text']; run['text'] = text
                run['usage'] = result.get('usage'); run['actual_model'] = result.get('model')
            value = {'id':uuid.uuid4().hex,'model':name,'choice':run['choice'],
                     'based_on':run['based_on'],'created_at':time.time(),
                     'actual_model':run.get('actual_model'),'requested_model':(run.get('config') or {}).get('model'),
                     'source_job':job_id,'usage':run.get('usage')}
            value['route' if stage == 'analysis' else 'answer' if stage == 'answer' else 'text'] = (
                parse_route(text,run['original']) if stage == 'analysis' else text.strip()[:12000])
            with owner.jobs.lock:
                session = owner.sessions[run['session']]
                versions = self.seed(session)[stage]
                versions.append(value); versions[:] = versions[-20:]
            owner._mark(job_id,name,state='completed',stage=labels[stage]+'复核完成',
                        version=value['id'],actual_model=run.get('actual_model'),
                        requested_model=value.get('requested_model'),completed_at=time.time())
            receipt = run['context'].get('receipt')
            if receipt:
                try:
                    provider.close_saved_response(receipt)
                    run['context']['receipt'] = None
                except Exception:
                    pass
        finally:
            if path:
                path.unlink(missing_ok=True)

    def retry(self, previous_id, restart=False):
        owner = self.owner
        with owner.intake_lock:
            previous = owner.jobs.items[previous_id]
            run = self.runs.get(previous_id)
            if not run:
                raise ValueError('复核记录已过期，请重新选择模型复核')
            if previous['state'] != 'failed':
                return {'id':previous_id,'session':run['session'],'resumed':True}
            active = next((key for key,r in self.runs.items() if r is run and
                owner.jobs.items.get(key,{}).get('state') == 'running'),None)
            if active:
                return {'id':active,'session':run['session'],'resumed':True}
            job_id = owner._reserve('ctrl-review-'+run['stage'],run['session'],[run['name']])
            owner.jobs.items[previous_id]['retry_id'] = job_id
            self.runs[job_id] = run
            owner._submit_model(job_id,run['name'],self.execute,previous_id,restart,priority=0)
            return {'id':job_id,'session':run['session']}

    def adopt(self, data):
        owner = self.owner
        with owner.intake_lock, owner.jobs.lock:
            session = owner.sessions.get(data.get('session'))
            if not session:
                raise ValueError('题目已过期')
            if any(j.get('session') == data['session'] and j['state'] == 'running' and
                   not j.get('kind','').startswith('ctrl-review') for j in owner.jobs.items.values()):
                raise ValueError('本题初始处理仍在进行，请完成后采用新原题')
            value = next((v for v in self.seed(session)['ocr'] if v['id'] == data.get('version')),None)
            if not value:
                raise ValueError('识题版本已过期')
            session['original'],session['original_revision'] = value['text'],value['id']
            return {'adopted':value['id']}

    def release(self, session_id):
        for job_id,run in list(self.runs.items()):
            if run['session'] == session_id:
                receipt = run['context'].pop('receipt',None)
                if receipt:
                    self.owner.model_pools[run['name']].submit(self.owner.providers[run['name']].close_saved_response,receipt)
                del self.runs[job_id]
