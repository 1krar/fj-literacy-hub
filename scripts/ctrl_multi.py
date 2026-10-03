"""Parallel CTRL workflows, preserving one browser conversation per model."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit
import re
import tempfile
import time
import uuid

from ctrl_assistant import OCR_PROMPT, ANSWER_PROMPT, ROOT, parse_route, route_prompt

MODELS = ('deepseek', 'gemini')


def selected_models(data):
    models = data.get('models', ['deepseek'])
    if (not isinstance(models, list) or not models or len(models) > 2 or len(set(models)) != len(models)
            or any(name not in MODELS for name in models)):
        raise ValueError('请选择 DeepSeek、Gemini 或两者')
    return models


class MultiCtrlJobs:
    def __init__(self, jobs, read_input):
        self.jobs = jobs
        self.read_input = read_input
        self.providers = jobs.providers
        self.sessions = {}

    def _reserve(self, kind, session_id, models):
        with self.jobs.lock:
            if self.jobs.active:
                raise RuntimeError('已有模型任务正在运行，请等待完成')
            if len(self.jobs.items) >= 20:
                del self.jobs.items[next(iter(self.jobs.items))]
            job_id = uuid.uuid4().hex
            self.jobs.active = job_id
            self.jobs.items[job_id] = {'id': job_id, 'kind': kind, 'session': session_id,
                                       'state': 'running', 'models': models,
                                       'results': {name: {'state': 'running', 'stage': '准备连接'} for name in models},
                                       'started_at': time.time()}
        return job_id

    def _mark(self, job_id, name, **fields):
        with self.jobs.lock:
            self.jobs.items[job_id]['results'][name].update(fields)

    def _finish(self, job_id):
        with self.jobs.lock:
            results = self.jobs.items[job_id]['results']
            success = any(item['state'] == 'completed' for item in results.values())
            self.jobs.items[job_id]['state'] = 'completed' if success else 'failed'
            self.jobs.items[job_id]['stage'] = '所选模型已处理完毕'
            self.jobs.active = None

    def _clean_old(self):
        # Keep the new conversation; close only tabs created by older CTRL runs.
        for session_id, session in list(self.sessions.items()):
            for name, model in session['models'].items():
                if model.get('receipt'):
                    try:
                        self.providers[name].close_saved_response(model['receipt'])
                    except Exception:
                        pass
            del self.sessions[session_id]

    def start(self, data):
        models = selected_models(data)
        text = data.get('text', '')
        image = data.get('image')
        if not isinstance(text, str) or len(text) > 10000:
            raise ValueError('原题文本超过10000字')
        text = text.strip()
        if not text and not image:
            raise ValueError('请粘贴原题文本或截图')
        raw, suffix = None, None
        if image:
            _, raw, suffix = self.read_input({'question': text or '截图', 'prompt': OCR_PROMPT, 'image': image})
        session_id = uuid.uuid4().hex
        job_id = self._reserve('ctrl-start', session_id, models)
        self._clean_old()
        self.sessions[session_id] = {'models': {name: {'original': '', 'route': None, 'answer': '', 'receipt': None}
                                                 for name in MODELS}, 'original': text if not raw else ''}
        self.jobs.pool.submit(self._run_start, job_id, session_id, models, text, raw, suffix)
        return {'id': job_id, 'session': session_id}

    def _run_start(self, job_id, session_id, models, text, raw, suffix):
        path = None
        try:
            if raw:
                folder = ROOT / '.runtime/uploads'
                folder.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=folder, suffix=suffix, delete=False) as file:
                    file.write(raw)
                    path = Path(file.name)
            with ThreadPoolExecutor(max_workers=len(models)) as pool:
                list(pool.map(lambda name: self._start_model(job_id, session_id, name, text, path), models))
        finally:
            if path:
                path.unlink(missing_ok=True)
            self._finish(job_id)

    def _start_model(self, job_id, session_id, name, text, path):
        model = self.sessions[session_id]['models'][name]
        provider = self.providers[name]
        try:
            if path:
                self._mark(job_id, name, stage='正在 OCR 识别截图')
                result = provider.generate_with_progress(OCR_PROMPT, path,
                    lambda stage: self._mark(job_id, name, stage=stage))
                if result.get('status') != 'completed' or not result.get('text', '').strip():
                    raise RuntimeError(result.get('detail') or '截图 OCR 未完成；请检查模型窗口')
                model['original'] = result['text'].strip()[:10000]
                model['receipt'] = result.get('cleanup_receipt')
                with self.jobs.lock:
                    if not self.sessions[session_id]['original']:
                        self.sessions[session_id]['original'] = model['original']
                self._mark(job_id, name, original=model['original'], stage='原题已识别，正在提取关键词和网站')
                result = self._continue(name, model, route_prompt(model['original']), job_id)
            else:
                model['original'] = text
                self._mark(job_id, name, original=text, stage='正在提取关键词和网站')
                result = provider.generate_with_progress('原题：\n'+text+'\n\n'+route_prompt(text), None,
                    lambda stage: self._mark(job_id, name, stage=stage))
                model['receipt'] = result.get('cleanup_receipt')
            if result.get('status') != 'completed':
                raise RuntimeError(result.get('detail') or '关键词和网站未完成')
            model['route'] = parse_route(result.get('text', ''))
            self._mark(job_id, name, state='completed', stage='关键词和网站已返回',
                       original=model['original'], route=model['route'], completed_at=time.time())
        except Exception as exc:
            self._mark(job_id, name, state='failed', stage='本模型未完成',
                       original=model['original'], error=str(exc)[:400], completed_at=time.time())

    def _find_page(self, browser, target_id):
        for context in browser.contexts:
            for page in context.pages:
                cdp = context.new_cdp_session(page)
                try:
                    current = cdp.send('Target.getTargetInfo')['targetInfo']['targetId']
                finally:
                    cdp.detach()
                if current == target_id:
                    return page
        return None

    def _continue(self, name, model, prompt, job_id):
        from playwright.sync_api import Error, TimeoutError as PlaywrightTimeout
        from evidence_chain.providers.ai.gemini_web import FinalResponseTracker
        provider = self.providers[name]
        transport = provider._transport
        receipt = model.get('receipt')
        owned = transport._owned_targets.get(receipt)
        if not owned:
            raise RuntimeError('原模型对话已丢失，请重新提交题目')
        with provider._lock:
            try:
                with transport._connection() as browser:
                    page = self._find_page(browser, owned['target_id'])
                    hostname = 'chat.deepseek.com' if name == 'deepseek' else 'gemini.google.com'
                    if not page or urlsplit(page.url).hostname != hostname:
                        raise RuntimeError('原模型对话已关闭或切换网站，请重新提交题目')
                    page.set_default_timeout(5000)
                    state = transport._page_state(page)
                    if state['status'] != 'ready':
                        raise RuntimeError(state.get('detail') or '模型窗口尚未就绪')
                    blocks = page.locator('.ds-markdown' if name == 'deepseek' else 'model-response')
                    before = blocks.count()
                    editor = transport._editor(page)
                    if editor is None:
                        raise RuntimeError('模型输入框不可用')
                    editor.fill(prompt)
                    if name == 'deepseek':
                        editor.press('Enter')
                    else:
                        send = transport._visible(page.get_by_role('button', name=re.compile(
                            r'^(Send|Send message|Submit|发送|提交|傳送)(訊息|消息)?$', re.I)))
                        transport._submit_once(editor, send)
                    self._mark(job_id, name, stage='已在同一对话追问，等待完整回复')
                    if name == 'gemini':
                        result = transport._await_response(page, before)
                        if result.get('status') != 'completed':
                            raise RuntimeError(result.get('detail') or 'Gemini 回复未确认完成')
                        return result
                    tracker = FinalResponseTracker(1)
                    deadline = time.monotonic() + 150
                    while time.monotonic() < deadline:
                        if transport._page_state(page)['status'] != 'ready':
                            raise RuntimeError('DeepSeek 页面需要登录或人工验证')
                        blocks = page.locator('.ds-markdown')
                        if blocks.count() > before:
                            block = blocks.last
                            answer = block.inner_text().strip()
                            stop = transport._visible(page.get_by_role('button', name=re.compile('停止|Stop', re.I)))
                            actions = transport._visible(block.locator('..').locator('..').get_by_role('button', name=re.compile('^(朗读|Read aloud)$', re.I)))
                            if tracker.observe(answer, actions is not None, stop is not None, time.monotonic()):
                                return {'status': 'completed', 'text': answer}
                        page.wait_for_timeout(350)
                    raise RuntimeError('DeepSeek 回复未确认完成；原对话已保留，未自动重发')
            except (Error, PlaywrightTimeout) as exc:
                raise RuntimeError('模型网页操作失败；请检查原对话，未自动重发') from exc

    def answer(self, data):
        session_id = data.get('session')
        session = self.sessions.get(session_id) if isinstance(session_id, str) else None
        if not session or not session['original']:
            raise ValueError('原题会话已过期，请重新提交题目')
        models = selected_models(data)
        job_id = self._reserve('ctrl-answer', session_id, models)
        self.jobs.pool.submit(self._run_answer, job_id, session_id, models)
        return {'id': job_id, 'session': session_id}

    def _run_answer(self, job_id, session_id, models):
        with ThreadPoolExecutor(max_workers=len(models)) as pool:
            list(pool.map(lambda name: self._answer_model(job_id, session_id, name), models))
        self._finish(job_id)

    def _answer_model(self, job_id, session_id, name):
        session = self.sessions[session_id]
        model = session['models'][name]
        try:
            self._mark(job_id, name, stage='正在询问答案')
            if model.get('receipt'):
                result = self._continue(name, model, ANSWER_PROMPT, job_id)
            else:
                original = session['original']
                result = self.providers[name].generate_with_progress('原题：\n'+original+'\n\n'+ANSWER_PROMPT,
                    None, lambda stage: self._mark(job_id, name, stage=stage))
                model['original'] = original
                model['receipt'] = result.get('cleanup_receipt')
            if result.get('status') != 'completed' or not result.get('text', '').strip():
                raise RuntimeError(result.get('detail') or '模型未返回完整答案')
            model['answer'] = result['text'].strip()[:12000]
            self._mark(job_id, name, state='completed', stage='答案已返回',
                       answer=model['answer'], completed_at=time.time())
        except Exception as exc:
            self._mark(job_id, name, state='failed', stage='作答未完成',
                       error=str(exc)[:400], completed_at=time.time())

    def get_session(self, session_id):
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError(session_id)
        return {'original': session['original'],
                'models': {name: {key: model[key] for key in ('original', 'route', 'answer')}
                           for name, model in session['models'].items()}}
