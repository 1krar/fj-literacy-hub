"""Parallel CTRL workflows, preserving one browser conversation per model."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
import re
import secrets
import tempfile
import threading
import time
import uuid

from ctrl_assistant import OCR_PROMPT, ANSWER_PROMPT, ROOT, parse_route, route_prompt

MODELS = ('deepseek', 'gemini')


class ConversationChanged(RuntimeError):
    """The visible page no longer proves it contains this request."""


class CtrlProgress:
    """Bind a fresh model request to its exact chat before accepting output."""

    def __init__(self, owner, job_id, name, model):
        self.owner, self.job_id, self.name, self.model = owner, job_id, name, model
        self.marker = 'CTRL-' + secrets.token_hex(6)
        self.initial_url = None
        self.key = None

    def prompt(self, value):
        return value + '\n[校验码 ' + self.marker + '，不属于题目]'

    def __call__(self, stage):
        self.owner._mark(self.job_id, self.name, stage=stage)

    def bind_page(self, page):
        self.initial_url = page.url
        transport = self.owner.providers[self.name]._transport
        owned = transport._owned_targets.get(transport._last_request_receipt)
        if owned:
            owned['guarded'] = True
            owned['url'] = page.url

    def before_send(self, page):
        initial = self.owner._conversation_key(self.name, self.initial_url)
        current = self.owner._conversation_key(self.name, page.url)
        if self.initial_url and (current != initial or (not initial and page.url != self.initial_url)):
            raise ConversationChanged('提交前模型标签已切换对话；未向其他对话发题')

    def after_send(self, page):
        # A unique marker in the submitted user message prevents binding to a
        # different conversation if navigation happens immediately after send.
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            key = self.owner._conversation_key(self.name, page.url)
            if key:
                submitted = page.evaluate("""marker => {
                    const body = document.body;
                    if (!body || !body.textContent.includes(marker)) return false;
                    return !Array.from(document.querySelectorAll('textarea, [contenteditable="true"]'))
                        .some(el => el.getClientRects().length &&
                            (el.value ?? el.textContent ?? '').includes(marker));
                }""", self.marker)
                if submitted:
                    self.key = key
                    self.model['conversation_url'] = page.url
                    transport = self.owner.providers[self.name]._transport
                    owned = transport._owned_targets.get(transport._last_request_receipt)
                    if owned:
                        owned['bound_url'] = page.url
                        owned['url'] = page.url
                    return
            page.wait_for_timeout(100)
        raise ConversationChanged('发送后未能确认本次消息所在的原对话；未采纳网页回复，请检查模型窗口')

    def check(self, page):
        if not self.key or self.owner._conversation_key(self.name, page.url) != self.key:
            raise ConversationChanged('模型标签已切换到另一段对话；未采纳该页面回复，请返回原对话后重试')

    def confirm_result(self, result):
        if (result.get('status') == 'completed' and
                self.owner._conversation_key(self.name, result.get('conversation_url')) != self.key):
            raise ConversationChanged('模型回复来自另一段或无法确认的对话；未采纳该回复')


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
        self.model_pools = {name: ThreadPoolExecutor(max_workers=1) for name in MODELS}
        self.intake_lock = threading.RLock()
        self.client_requests = {}

    def shutdown(self, wait=True):
        for pool in self.model_pools.values():
            pool.shutdown(wait=wait)

    def wait_idle(self):
        for pool in self.model_pools.values():
            pool.submit(lambda: None).result()

    def _reserve(self, kind, session_id, models):
        with self.jobs.lock:
            if len(self.jobs.items) >= 100:
                removable = next((key for key, item in self.jobs.items.items()
                                  if item['state'] != 'running'), None)
                if removable:
                    del self.jobs.items[removable]
            job_id = uuid.uuid4().hex
            self.jobs.items[job_id] = {'id': job_id, 'kind': kind, 'session': session_id,
                                       'state': 'running', 'models': models,
                                     'results': {name: {'state': 'queued', 'stage': '排队等待模型'} for name in models},
                                       'started_at': time.time()}
        return job_id

    def _mark(self, job_id, name, **fields):
        with self.jobs.lock:
            self.jobs.items[job_id]['results'][name].update(fields)

    def _finish(self, job_id):
        with self.jobs.lock:
            results = self.jobs.items[job_id]['results']
            if any(item['state'] in ('queued', 'running') for item in results.values()):
                return
            success = any(item['state'] == 'completed' for item in results.values())
            self.jobs.items[job_id]['state'] = 'completed' if success else 'failed'
            self.jobs.items[job_id]['stage'] = '所选模型已处理完毕'

    def _submit_model(self, job_id, name, work, *args):
        def run():
            self._mark(job_id, name, state='running')
            try:
                work(job_id, *args, name)
            except Exception as exc:
                self._mark(job_id, name, state='failed', error=str(exc)[:400],
                           completed_at=time.time())
            finally:
                self._finish(job_id)
        self.model_pools[name].submit(run)

    def _clean_old(self):
        # Keep recent task conversations for switching and follow-up answers.
        while len(self.sessions) > 20:
            with self.jobs.lock:
                running = {item['session'] for item in self.jobs.items.values()
                           if item['state'] == 'running' and 'session' in item}
            session_id = next((key for key in self.sessions if key not in running), None)
            if not session_id:
                return
            session = self.sessions[session_id]
            for name, model in session['models'].items():
                if model.get('receipt'):
                    self.model_pools[name].submit(self.providers[name].close_saved_response, model['receipt'])
            del self.sessions[session_id]
            if session.get('client_id'):
                self.client_requests.pop(session['client_id'], None)

    def start(self, data):
        with self.intake_lock:
            return self._start(data)

    def _start(self, data):
        client_id = data.get('client_id')
        if client_id is not None and (not isinstance(client_id, str) or
                                      not re.fullmatch(r'[\w-]{1,100}', client_id)):
            raise ValueError('提交编号无效')
        if client_id and client_id in self.client_requests:
            return dict(self.client_requests[client_id])
        with self.jobs.lock:
            running = {item.get('session') for item in self.jobs.items.values()
                       if item.get('kind', '').startswith('ctrl-') and item['state'] == 'running'}
        if len(running) >= 20:
            raise ValueError('队列已有20道正在处理的题目；请等部分完成后再提交，当前截图仍可重试')
        models = selected_models(data)
        fast_answer = data.get('fast_answer', False)
        if not isinstance(fast_answer, bool):
            raise ValueError('快答选项无效')
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
        self.sessions[session_id] = {'models': {name: {'original': '', 'route': None, 'answer': '', 'receipt': None,
                                                     'phase': 'preparing'} for name in MODELS},
                                     'original': text if not raw else '', 'input_text': text,
                                     'had_image': bool(raw), 'image': raw, 'image_suffix': suffix,
                                     'created_at': time.time(), 'fast_answer': fast_answer,
                                     'client_id': client_id}
        if client_id:
            self.client_requests[client_id] = {'id': job_id, 'session': session_id}
        for name in models:
            self._submit_model(job_id, name, self._start_queued, session_id, text, raw, suffix)
        self._clean_old()
        return {'id': job_id, 'session': session_id}

    def _start_queued(self, job_id, session_id, text, raw, suffix, name):
        path = None
        try:
            if raw:
                folder = ROOT / '.runtime/uploads'
                folder.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=folder, suffix=suffix, delete=False) as file:
                    file.write(raw)
                    path = Path(file.name)
            self._start_model(job_id, session_id, name, text, path)
        finally:
            if path:
                path.unlink(missing_ok=True)

    def _start_model(self, job_id, session_id, name, text, path):
        model = self.sessions[session_id]['models'][name]
        provider = self.providers[name]
        try:
            progress = CtrlProgress(self, job_id, name, model)
            model['guarded'] = hasattr(provider, '_transport')
            if path:
                model['phase'] = 'ocr'
                self._mark(job_id, name, stage='正在 OCR 识别截图')
                result = provider.generate_with_progress(progress.prompt(OCR_PROMPT), path, progress)
                model['receipt'] = result.get('cleanup_receipt')
                if model['guarded'] and not progress.key:
                    raise ConversationChanged('未确认截图 OCR 所属对话；未采纳回复')
                if model['guarded']:
                    progress.confirm_result(result)
                if result.get('status') != 'completed' or not result.get('text', '').strip():
                    raise RuntimeError(result.get('detail') or '截图 OCR 未完成；请检查模型窗口')
                model['original'] = result['text'].replace(progress.marker, '').strip()[:10000]
                model['receipt'] = result.get('cleanup_receipt')
                model['phase'] = 'ocr_done'
                with self.jobs.lock:
                    if not self.sessions[session_id]['original']:
                        self.sessions[session_id]['original'] = model['original']
                self._mark(job_id, name, original=model['original'], stage='原题已识别，正在提取关键词和网站')
                result = self._continue(name, model, route_prompt(model['original'],
                    self.sessions[session_id].get('fast_answer', False)), job_id)
            else:
                model['original'] = text
                model['phase'] = 'route'
                self._mark(job_id, name, original=text, stage='正在提取关键词和网站')
                result = provider.generate_with_progress(progress.prompt('原题：\n'+text+'\n\n'+route_prompt(text,
                    self.sessions[session_id].get('fast_answer', False))),
                    None, progress)
                model['receipt'] = result.get('cleanup_receipt')
                if model['guarded'] and not progress.key:
                    raise ConversationChanged('未确认检索建议所属对话；未采纳回复')
                if model['guarded']:
                    progress.confirm_result(result)
            if result.get('status') != 'completed':
                raise RuntimeError(result.get('detail') or '关键词和网站未完成')
            model['route'] = parse_route(result.get('text', ''), model['original'])
            if self.sessions[session_id].get('fast_answer'):
                model['answer'] = model['route'].pop('answer', '')
            model['phase'] = 'route_done'
            self._mark(job_id, name, state='completed', stage='关键词和网站已返回',
                       original=model['original'], route=model['route'], answer=model['answer'],
                       completed_at=time.time())
        except Exception as exc:
            transport = getattr(provider, '_transport', None)
            receipt = getattr(transport, '_last_request_receipt', None)
            if receipt and receipt in getattr(transport, '_owned_targets', {}):
                model['receipt'] = receipt
            self._mark(job_id, name, state='failed', stage='本模型未完成',
                       original=model['original'], error=str(exc)[:400], completed_at=time.time())

    def _find_page(self, browser, target_id):
        for context in browser.contexts:
            for page in context.pages:
                if self._page_target_id(page) == target_id:
                    return page
        return None

    @staticmethod
    def _page_target_id(page):
        cdp = page.context.new_cdp_session(page)
        try:
            return cdp.send('Target.getTargetInfo')['targetInfo']['targetId']
        finally:
            cdp.detach()

    @staticmethod
    def _conversation_key(name, url):
        """Only an actual conversation path can identify a chat, not a home URL."""
        parts = urlsplit(url or '')
        path = parts.path.rstrip('/')
        if parts.scheme != 'https' or parts.username or parts.password:
            return None
        if name == 'deepseek' and parts.hostname == 'chat.deepseek.com' and re.fullmatch(r'/a/chat/s/[\w-]+', path):
            return (parts.hostname, path)
        if name == 'gemini' and parts.hostname == 'gemini.google.com' and re.fullmatch(r'/app/[\w-]+', path):
            return (parts.hostname, path)
        return None

    def _locate_conversation(self, browser, name, owned):
        """Bind to the saved chat, even when the user moved it to another tab."""
        saved_url = owned.get('bound_url') or owned.get('url')
        expected = self._conversation_key(name, saved_url)
        current = self._find_page(browser, owned['target_id'])
        hostname = 'chat.deepseek.com' if name == 'deepseek' else 'gemini.google.com'
        if current and urlsplit(current.url).hostname == hostname:
            if (self._conversation_key(name, current.url) == expected and expected) or (
                    not expected and current.url == owned.get('url')):
                return current
        if not expected:
            return None
        for context in browser.contexts:
            for page in context.pages:
                if self._conversation_key(name, page.url) == expected:
                    # This may be a tab opened by the user. Use it for this
                    # request, but never reassign the cleanup receipt to it.
                    return page
        # Reuse the original tab. Some model sites challenge a freshly opened
        # tab even in the same browser profile; the user approved this return.
        if not current:
            return None
        try:
            current.goto(saved_url, wait_until='domcontentloaded', timeout=20000)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if self._conversation_key(name, current.url) == expected:
                    state = self.providers[name]._transport._page_state(current)
                    if state['status'] == 'ready':
                        return current
                    if state['status'] in ('login_required', 'human_required'):
                        raise RuntimeError(state.get('detail') or '模型窗口需要登录或验证')
                current.wait_for_timeout(250)
        except RuntimeError:
            raise
        except Exception:
            pass
        raise RuntimeError('原对话暂时打不开；未采纳其他对话回复，也未自动重发')

    def _assert_bound_conversation(self, name, page, owned):
        expected = self._conversation_key(name, owned.get('bound_url') or owned.get('url'))
        if not expected or self._conversation_key(name, page.url) != expected:
            raise ConversationChanged('模型标签已切换到另一段对话；未采纳该页面回复，请点重试返回原对话')

    def _continue(self, name, model, prompt, job_id):
        from playwright.sync_api import Error, TimeoutError as PlaywrightTimeout
        from evidence_chain.providers.ai.gemini_web import FinalResponseTracker
        provider = self.providers[name]
        transport = provider._transport
        receipt = model.get('receipt')
        owned = transport._owned_targets.get(receipt)
        if not owned:
            raise RuntimeError('原模型对话已丢失，请重新提交题目')
        if model.get('guarded') and not owned.get('bound_url'):
            raise ConversationChanged('原对话地址未确认，未向其他对话发送追问')
        with provider._lock:
            try:
                with transport._connection(wake=True) as browser:
                    page = self._locate_conversation(browser, name, owned)
                    if not page:
                        raise RuntimeError('未能定位原模型对话；请检查原窗口后重试')
                    self._assert_bound_conversation(name, page, owned)
                    page.set_default_timeout(5000)
                    state = transport._page_state(page)
                    if state['status'] != 'ready':
                        raise RuntimeError(state.get('detail') or '模型窗口尚未就绪')
                    blocks = page.locator('.ds-markdown' if name == 'deepseek' else 'model-response')
                    before = blocks.count()
                    model['response_before'] = before
                    editor = transport._editor(page)
                    if editor is None:
                        raise RuntimeError('模型输入框不可用')
                    model['phase'] = 'answer_sending' if prompt == ANSWER_PROMPT else 'route_sending'
                    editor.fill(prompt)
                    if name == 'deepseek':
                        editor.press('Enter')
                    else:
                        send = transport._visible(page.get_by_role('button', name=re.compile(
                            r'^(Send|Send message|Submit|发送|提交|傳送)(訊息|消息)?$', re.I)))
                        transport._submit_once(editor, send)
                    self._assert_bound_conversation(name, page, owned)
                    model['phase'] = 'answer_sent' if prompt == ANSWER_PROMPT else 'route_sent'
                    self._mark(job_id, name, stage='已在同一对话追问，等待完整回复')
                    if name == 'gemini':
                        result = transport._await_response(page, before,
                            progress=SimpleNamespace(check=lambda current: self._assert_bound_conversation(name, current, owned)))
                        if result.get('status') != 'completed':
                            raise RuntimeError(result.get('detail') or 'Gemini 回复未确认完成')
                        self._assert_bound_conversation(name, page, owned)
                        return result
                    tracker = FinalResponseTracker(1)
                    deadline = time.monotonic() + 150
                    while time.monotonic() < deadline:
                        self._assert_bound_conversation(name, page, owned)
                        if transport._page_state(page)['status'] != 'ready':
                            raise RuntimeError('DeepSeek 页面需要登录或人工验证')
                        blocks = page.locator('.ds-markdown')
                        if blocks.count() > before:
                            block = blocks.last
                            answer = block.inner_text().strip()
                            stop = transport._visible(page.get_by_role('button', name=re.compile('停止|Stop', re.I)))
                            actions = transport._visible(block.locator('..').locator('..').get_by_role('button', name=re.compile('^(朗读|Read aloud)$', re.I)))
                            if tracker.observe(answer, actions is not None, stop is not None, time.monotonic()):
                                self._assert_bound_conversation(name, page, owned)
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
        for name in models:
            self._submit_model(job_id, name, self._answer_queued, session_id)
        return {'id': job_id, 'session': session_id}

    def _answer_queued(self, job_id, session_id, name):
        self._answer_model(job_id, session_id, name)

    def _answer_model(self, job_id, session_id, name):
        session = self.sessions[session_id]
        model = session['models'][name]
        try:
            self._mark(job_id, name, stage='正在询问答案')
            if model.get('receipt'):
                result = self._continue(name, model, ANSWER_PROMPT, job_id)
            else:
                original = session['original']
                model['phase'] = 'answer'
                progress = CtrlProgress(self, job_id, name, model)
                model['guarded'] = hasattr(self.providers[name], '_transport')
                result = self.providers[name].generate_with_progress(
                    progress.prompt('原题：\n'+original+'\n\n'+ANSWER_PROMPT), None, progress)
                model['original'] = original
                model['receipt'] = result.get('cleanup_receipt')
                if model['guarded'] and not progress.key:
                    raise ConversationChanged('未确认直接作答所属对话；未采纳回复')
                if model['guarded']:
                    progress.confirm_result(result)
            if result.get('status') != 'completed' or not result.get('text', '').strip():
                raise RuntimeError(result.get('detail') or '模型未返回完整答案')
            model['answer'] = result['text'].strip()[:12000]
            model['phase'] = 'answer_done'
            self._mark(job_id, name, state='completed', stage='答案已返回',
                       answer=model['answer'], completed_at=time.time())
        except Exception as exc:
            transport = getattr(self.providers[name], '_transport', None)
            receipt = getattr(transport, '_last_request_receipt', None)
            if receipt and receipt in getattr(transport, '_owned_targets', {}):
                model['receipt'] = receipt
            self._mark(job_id, name, state='failed', stage='作答未完成',
                       error=str(exc)[:400], completed_at=time.time())

    def retry(self, data):
        previous_id = data.get('job')
        if not isinstance(previous_id, str):
            raise ValueError('缺少原任务编号，请重新提交题目')
        try:
            previous = self.jobs.get(previous_id)
        except KeyError as exc:
            raise ValueError('原任务已过期，请重新提交题目') from exc
        if previous.get('kind') not in ('ctrl-start', 'ctrl-answer', 'ctrl-retry-start', 'ctrl-retry-answer'):
            raise ValueError('原任务不是 CTRL 助手任务')
        if previous['state'] == 'running':
            return {'id': previous_id, 'session': previous['session'], 'resumed': True}
        failed = [name for name, value in previous['results'].items() if value['state'] == 'failed']
        if not failed:
            return {'id': previous_id, 'session': previous['session'], 'resumed': True}
        session_id = previous['session']
        current = self.sessions.get(session_id)
        if not current:
            raise ValueError('本机会话已过期，请重新提交题目')
        kind = 'answer' if previous['kind'].endswith('answer') else 'start'
        image = data.get('image')
        raw, suffix = None, None
        if kind == 'start' and current['had_image'] and any(not current['models'][name]['original'] for name in failed):
            raw, suffix = current.get('image'), current.get('image_suffix')
            if not raw and image:
                _, raw, suffix = self.read_input({'question': current['input_text'] or '截图',
                                                   'prompt': OCR_PROMPT, 'image': image})
        job_id = self._reserve('ctrl-retry-'+kind, session_id, failed)
        for name in failed:
            self._submit_model(job_id, name, self._retry_queued, session_id, kind, raw, suffix)
        return {'id': job_id, 'session': session_id, 'retried': failed}

    def _retry_queued(self, job_id, session_id, kind, raw, suffix, name):
        path = None
        try:
            if raw:
                folder = ROOT / '.runtime/uploads'
                folder.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=folder, suffix=suffix, delete=False) as file:
                    file.write(raw)
                    path = Path(file.name)
            self._retry_model(job_id, session_id, kind, name, path)
        finally:
            if path:
                path.unlink(missing_ok=True)

    def _read_saved_reply(self, name, model):
        """Read a confirmed final reply from the owned tab; never submit here."""
        from evidence_chain.providers.ai.gemini_web import BrowserUnavailable, FinalResponseTracker
        provider = self.providers[name]
        transport = provider._transport
        owned = transport._owned_targets.get(model.get('receipt'))
        if not owned:
            return None
        if model.get('guarded') and not owned.get('bound_url'):
            raise ConversationChanged('本次发送后未能确认原对话地址；无法安全读取，请重新提交题目')
        with provider._lock:
            try:
                connection = transport._connection(wake=True)
                browser = connection.__enter__()
            except BrowserUnavailable:
                return None
            try:
                page = self._locate_conversation(browser, name, owned)
                if not page:
                    return None
                blocks = page.locator('.ds-markdown' if name == 'deepseek' else 'model-response')
                tracker = FinalResponseTracker(1)
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    self._assert_bound_conversation(name, page, owned)
                    state = transport._page_state(page)
                    if state['status'] != 'ready':
                        raise RuntimeError(state.get('detail') or '原模型网页尚未就绪')
                    minimum = model.get('response_before', 0) if model.get('phase') in ('route_sent', 'answer_sent', 'route_sending', 'answer_sending') else 0
                    if blocks.count() > minimum:
                        block = blocks.last
                        if name == 'deepseek':
                            answer = block.inner_text().strip()
                            actions = transport._visible(block.locator('..').locator('..').get_by_role(
                                'button', name=re.compile('^(朗读|Read aloud)$', re.I)))
                        else:
                            content = block.locator('message-content .markdown, .model-response-text .markdown, message-content')
                            answer = content.first.inner_text().strip() if content.count() else ''
                            actions = transport._visible(block.get_by_role('button', name=re.compile(
                                'copy|复制|複製|good response|bad response|回答得好|回答得不好', re.I)))
                        stop = transport._visible(page.get_by_role('button', name=re.compile(
                            '停止|Stop|stop response|stop generating', re.I)))
                        if tracker.observe(answer, actions is not None, stop is not None, time.monotonic()):
                            self._assert_bound_conversation(name, page, owned)
                            return answer
                    page.wait_for_timeout(350)
                raise RuntimeError('原对话仍在，但尚未确认完整回复；请稍后再点重试，未重复发送')
            finally:
                connection.__exit__(None, None, None)

    def _retry_model(self, job_id, session_id, kind, name, path):
        session = self.sessions[session_id]
        model = session['models'][name]
        try:
            self._mark(job_id, name, stage='正在读取原模型对话')
            reply = self._read_saved_reply(name, model) if model.get('receipt') else None
            if kind == 'answer':
                if reply:
                    model['answer'] = reply[:12000]
                else:
                    self._mark(job_id, name, stage='原对话已消失，正在新会话询问答案')
                    model['receipt'] = None
                    self._answer_model(job_id, session_id, name)
                    return
                model['phase'] = 'answer_done'
                self._mark(job_id, name, state='completed', stage='已从原对话取回答案',
                           answer=model['answer'], completed_at=time.time())
                return
            if reply:
                if not model['original']:
                    model['original'] = reply.strip()[:10000]
                    if not session['original']:
                        session['original'] = model['original']
                    self._mark(job_id, name, original=model['original'], stage='已取回原题，继续检索建议')
                    result = self._continue(name, model, route_prompt(model['original'],
                        session.get('fast_answer', False)), job_id)
                    if result.get('status') != 'completed':
                        raise RuntimeError(result.get('detail') or '检索建议未完成')
                    reply = result.get('text', '')
                elif model['phase'] == 'ocr_done':
                    self._mark(job_id, name, original=model['original'], stage='继续生成检索建议')
                    result = self._continue(name, model, route_prompt(model['original'],
                        session.get('fast_answer', False)), job_id)
                    if result.get('status') != 'completed':
                        raise RuntimeError(result.get('detail') or '检索建议未完成')
                    reply = result.get('text', '')
                model['route'] = parse_route(reply, model['original'])
                if session.get('fast_answer'):
                    model['answer'] = model['route'].pop('answer', '')
            else:
                self._mark(job_id, name, stage='原对话已消失，正在新会话重新识题')
                if session['had_image'] and not model['original'] and not path:
                    raise RuntimeError('原对话已消失；请重新粘贴原截图后重试')
                model['receipt'] = None
                self._start_model(job_id, session_id, name, model['original'] or session['input_text'], path)
                return
            model['phase'] = 'route_done'
            self._mark(job_id, name, state='completed', stage='已从原对话取回检索建议',
                       original=model['original'], route=model['route'], answer=model['answer'],
                       completed_at=time.time())
        except Exception as exc:
            self._mark(job_id, name, state='failed', stage='重试未完成',
                       original=model['original'], error=str(exc)[:400], completed_at=time.time())

    def get_session(self, session_id):
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError(session_id)
        with self.jobs.lock:
            jobs = [item for item in self.jobs.items.values() if item.get('session') == session_id]
            activity = {}
            for item in jobs:
                activity.update({name: dict(value) for name, value in item['results'].items()})
            state = 'running' if any(item['state'] == 'running' for item in jobs) else (
                jobs[-1]['state'] if jobs else 'completed')
        return {'original': session['original'], 'state': state, 'activity': activity,
                'job': jobs[-1]['id'] if jobs else None,
                'started_at': session.get('created_at') or (jobs[-1].get('started_at') if jobs else None),
                'created_at': session.get('created_at'),
                'models': {name: {key: model[key] for key in ('original', 'route', 'answer')}
                           for name, model in session['models'].items()}}

    def list_tasks(self):
        tasks = []
        with self.jobs.lock:
            items = list(self.jobs.items.values())
        for session_id, session in list(self.sessions.items()):
            jobs = [item for item in items if item.get('session') == session_id]
            current = jobs[-1] if jobs else None
            activity = {}
            for item in jobs:
                activity.update(item['results'])
            title = (session['original'] or session['input_text'] or '截图识别中').replace('\n', ' ').strip()
            tasks.append({'session': session_id, 'title': title[:45],
                          'client_id': session.get('client_id'),
                          'created_at': session.get('created_at'),
                          'job': current['id'] if current else None,
                          'state': 'running' if any(item['state'] == 'running' for item in jobs)
                                   else current['state'] if current else 'completed',
                          'ready': any(model.get('route') for model in session['models'].values()),
                          'has_original': bool(session['original']),
                          'has_failure': any(value['state'] == 'failed' for value in activity.values()),
                          'had_image': session['had_image']})
        return tasks

    def archive(self, data):
        session_id = data.get('session')
        with self.intake_lock:
            session = self.sessions.get(session_id)
            if not session:
                raise ValueError('题目已过期')
            with self.jobs.lock:
                if any(item.get('session') == session_id and item['state'] == 'running'
                       for item in self.jobs.items.values()):
                    raise ValueError('当前题仍在处理，请完成后归档')
            for name, model in session['models'].items():
                receipt = model.get('receipt')
                if receipt:
                    self.model_pools[name].submit(self.providers[name].close_saved_response, receipt)
            del self.sessions[session_id]
            if session.get('client_id'):
                self.client_requests.pop(session['client_id'], None)
        return {'archived': True}

    def get_image(self, session_id):
        session = self.sessions.get(session_id)
        if not session:
            raise KeyError(session_id)
        return session.get('image'), session.get('image_suffix')

