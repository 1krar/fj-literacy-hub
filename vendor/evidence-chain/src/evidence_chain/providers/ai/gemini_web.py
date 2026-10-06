"""Gemini website adapter using a separately logged-in, local browser.

No API key or exported browser credentials are used. The CDP connection is
disconnected after each operation without closing the browser or its tabs.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen
from uuid import uuid4


GEMINI_URL = "https://gemini.google.com/app"
PROVIDER = "gemini_web"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_cdp_url(value: str) -> str:
    parsed = urlparse(value)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"} or not parsed.port):
        raise ValueError("Gemini browser endpoint must be a loopback HTTP URL with an explicit port")
    return value.rstrip("/")


class GeminiWebProvider:
    provider_id = PROVIDER
    def __init__(self, cdp_url: str | None = None, *, timeout_seconds: float = 180,
                 profile_dir: Path | None = None, transport: Any = None):
        endpoint = validate_cdp_url(cdp_url or os.environ.get("EVIDENCE_CHAIN_GEMINI_CDP_URL", "http://127.0.0.1:9230"))
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        profile = profile_dir or Path(__file__).resolve().parents[4] / ".runtime" / "gemini-browser"
        self._transport = transport or GeminiBrowserTransport(endpoint, profile, timeout_seconds)
        self._lock = threading.Lock()
        self._active_method = None

    def start_browser(self) -> dict[str, Any]:
        return self._run("start_browser")

    def status(self) -> dict[str, Any]:
        return self._run("status")

    def close_saved_response(self, receipt):
        return self._run('close_saved_response', receipt)

    def generate(self, prompt: str) -> dict[str, Any]:
        return self._generate(prompt)

    def generate_with_progress(self, prompt, image_path, progress):
        return self._generate(prompt, image_path, progress)

    def generate_with_image(self, prompt: str, image_path: Path) -> dict[str, Any]:
        if not image_path.is_file():
            raise ValueError("Image does not exist")
        return self._generate(prompt, image_path)

    def _generate(self, prompt: str, image_path: Path | None = None, progress=None) -> dict[str, Any]:
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 24000:
            raise ValueError("Prompt must contain 1 to 24000 characters")
        started = utc_now()
        if progress:
            result = self._run('generate', prompt.strip(), image_path, progress)
        else:
            result = self._run("generate", prompt.strip(), image_path) if image_path else self._run("generate", prompt.strip())
        result.update({"request_id": str(uuid4()), "started_at": started, "completed_at": utc_now(),
                       "is_evidence": False, "input": prompt.strip()})
        if result["status"] == "completed" and not result.get("text", "").strip():
            result.update(status="error", detail="Gemini returned no final response", text="")
        return result

    def _run(self, method: str, *args: Any) -> dict[str, Any]:
        acquired = self._lock.acquire(blocking=False)
        if not acquired and method == 'generate' and self._active_method == 'status':
            acquired = self._lock.acquire(timeout=15)
        if not acquired:
            return {"status": "busy", "provider": self.provider_id, "detail": "Website model is processing another request", "text": ""}
        self._active_method = method
        try:
            try:
                result = dict(getattr(self._transport, method)(*args))
            except ImportError:
                result = {"status": "unavailable", "detail": "Playwright is not installed; install the gemini-web extra"}
            except (OSError, URLError):
                result = {"status": "unavailable", "detail": "Cannot connect to the local Gemini browser"}
            result.setdefault("provider", self.provider_id)
            result.setdefault("text", "")
            return result
        finally:
            self._active_method = None
            self._lock.release()

    def close(self) -> None:
        """The user owns the visible browser after launch; leave it running."""


class GeminiBrowserTransport:
    home_url = GEMINI_URL
    def __init__(self, cdp_url: str, profile_dir: Path, timeout_seconds: float):
        self.cdp_url = cdp_url
        self.profile_dir = profile_dir
        self.timeout_seconds = timeout_seconds
        self._owned_targets = {}
        self._tracking_pages = {}
        self._last_request_receipt = None

    def close_saved_response(self, receipt):
        owned = self._owned_targets.get(receipt)
        if not owned:
            return {'status': 'not_owned'}
        with self._connection() as browser:
            session = browser.new_browser_cdp_session()
            try:
                info = session.send('Target.getTargetInfo', {'targetId': owned['target_id']})['targetInfo']
                if info.get('type') != 'page' or info.get('url') != owned['url']:
                    return {'status': 'changed', 'detail': '页面已改变，保留标签'}
                # Keep a warm home tab when closing the last task tab.
                if sum(len(context.pages) for context in browser.contexts) <= 1:
                    if not browser.contexts:
                        return {'status': 'retained'}
                    keeper = browser.contexts[0].new_page()
                    keeper.goto(self.home_url, wait_until='domcontentloaded', timeout=30000)
                result = session.send('Target.closeTarget', {'targetId': owned['target_id']})
                if result.get('success'):
                    del self._owned_targets[receipt]
                    return {'status': 'closed'}
                return {'status': 'retained'}
            finally:
                session.detach()

    def _listening(self) -> bool:
        try:
            with urlopen(self.cdp_url + "/json/version", timeout=.7) as response:
                payload = json.load(response)
            return isinstance(payload.get("Browser"), str)
        except (OSError, ValueError, URLError):
            return False

    def start_browser(self) -> dict[str, Any]:
        already_running = self._listening()
        executable = self._browser_executable()
        if not executable:
            return {"status": "unavailable", "detail": "Google Chrome or Microsoft Edge was not found"}
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        port = urlparse(self.cdp_url).port
        process = subprocess.Popen([executable, f"--remote-debugging-port={port}",
                          "--remote-debugging-address=127.0.0.1",
                          f"--user-data-dir={self.profile_dir.resolve()}",
                          "--no-first-run", "--no-default-browser-check", "--new-window", self.home_url],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        if already_running:
            return {"status": "window_opened", "detail": "已请求在原登录配置中新建 Gemini 窗口；连接状态尚待确认。",
                    "url": GEMINI_URL}
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self._listening():
                return {"status": "window_opened", "detail": "已打开 Gemini 窗口并复用原登录配置；若需登录，请在窗口中完成。",
                        "url": GEMINI_URL}
            if process.poll() is not None:
                break
            time.sleep(.25)
        return {"status": "launch_failed", "detail": "Browser did not open its local connection. Check launch permissions and retry.", "url": GEMINI_URL}

    @staticmethod
    def _browser_executable() -> str | None:
        roots = [os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", ""),
                 os.environ.get("LOCALAPPDATA", "")]
        for relative in ("Google/Chrome/Application/chrome.exe", "Microsoft/Edge/Application/msedge.exe"):
            for root in roots:
                candidate = Path(root) / relative
                if root and candidate.is_file():
                    return str(candidate)
        return shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("msedge")

    @contextmanager
    def _connection(self, wake=False):
        from playwright.sync_api import Error, sync_playwright
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.connect_over_cdp(self.cdp_url, timeout=10000, no_defaults=True)
            except Error as exc:
                if not wake or not self._wake_gemini_pages():
                    raise BrowserUnavailable() from exc
                try:
                    browser = playwright.chromium.connect_over_cdp(self.cdp_url, timeout=10000, no_defaults=True)
                except Error as retry_error:
                    raise BrowserUnavailable() from retry_error
            try:
                yield browser
            finally:
                # Capture the final URL before disconnecting Playwright. Never close
                # a tab later if the user has navigated it to another page.
                for receipt, page in self._tracking_pages.items():
                    try:
                        if receipt in self._owned_targets:
                            owned = self._owned_targets[receipt]
                            if owned.get('bound_url'):
                                owned['url'] = owned['bound_url']
                            elif not owned.get('guarded'):
                                owned['url'] = page.url
                    except Error:
                        pass
                self._tracking_pages.clear()

    def _wake_gemini_pages(self):
        """Activate existing Gemini tabs only; never navigate, close, or submit."""
        try:
            with urlopen(self.cdp_url+'/json/list',timeout=2) as response:
                targets=json.load(response)
            if not isinstance(targets,list):return False
            activated=False
            for target in targets[:50]:
                parsed=urlparse(target.get('url',''))
                target_id=target.get('id','')
                if (target.get('type')!='page' or parsed.scheme!='https' or parsed.hostname!='gemini.google.com'
                    or parsed.username or parsed.password or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',target_id)):
                    continue
                with urlopen(self.cdp_url+'/json/activate/'+target_id,timeout=2) as response:
                    response.read(200)
                activated=True
            return activated
        except (OSError,ValueError,URLError,TypeError):
            return False

    def status(self) -> dict[str, Any]:
        from playwright.sync_api import Error
        if not self._listening():
            return {"status": "unavailable", "detail": "Open the dedicated Gemini browser first", "url": GEMINI_URL}
        try:
            with self._connection() as browser:
                pages = [page for context in browser.contexts for page in context.pages
                         if urlparse(page.url).hostname == "gemini.google.com"]
                if not pages:
                    return {"status": "unavailable", "detail": "未打开 Gemini 标签；可新建窗口复用原登录状态，尚未判断是否需要登录", "url": GEMINI_URL}
                for page in reversed(pages):
                    try:
                        page.set_default_timeout(3000)
                        state = self._page_state(page)
                    except Error:
                        state = {"status": "unavailable", "detail": "A Gemini tab needs attention; inspect the dedicated browser", "url": GEMINI_URL}
                        continue
                    if state["status"] == "ready":
                        return state
                return state
        except (BrowserUnavailable, Error):
            return {"status": "unavailable", "detail": "Gemini browser connection is unavailable", "url": GEMINI_URL}

    @staticmethod
    def _visible(locator):
        for index in range(locator.count()):
            item = locator.nth(index)
            if item.is_visible():
                return item
        return None

    def _editor(self, page):
        return self._visible(page.locator('rich-textarea [contenteditable="true"], [contenteditable="true"][role="textbox"], textarea[aria-label]'))

    def _page_state(self, page) -> dict[str, Any]:
        hostname = urlparse(page.url).hostname or ""
        if hostname == "accounts.google.com":
            return {"status": "login_required", "detail": "Sign in to Google in the Gemini browser", "url": page.url}
        sign_in = self._visible(page.get_by_role("link", name=re.compile(r"^(Sign in|登录|登入)$", re.I)))
        sign_in = sign_in or self._visible(page.get_by_role("button", name=re.compile(r"^(Sign in|登录|登入)$", re.I)))
        if sign_in:
            return {"status": "login_required", "detail": "Gemini requires sign-in in the dedicated browser", "url": GEMINI_URL}
        if self._visible(page.locator('iframe[src*="recaptcha"][src*="bframe"], iframe[title*="challenge"], iframe[title*="验证"]')):
            return {"status": "human_required", "detail": "Complete the verification in the Gemini browser", "url": GEMINI_URL}
        quota = self._visible(page.locator('[role="alert"], [role="status"]').filter(
            has_text=re.compile(r"you.*reached.*limit|已达到.*(?:使用|次数|请求).*上限|已达.*限额", re.I)))
        if quota:
            return {"status": "rate_limited", "detail": "Gemini website reports a usage limit; inspect the browser", "url": GEMINI_URL}
        if self._editor(page):
            return {"status": "ready", "detail": "Gemini website is ready", "url": page.url}
        return {"status": "unavailable", "detail": "Gemini page is loading or needs attention in the browser", "url": page.url}

    def _new_task_page(self, browser):
        page = browser.contexts[0].new_page()
        session = page.context.new_cdp_session(page)
        try:
            target = session.send('Target.getTargetInfo')['targetInfo']['targetId']
        finally:
            session.detach()
        receipt = uuid4().hex
        self._owned_targets[receipt] = {'target_id': target, 'url': page.url}
        self._tracking_pages[receipt] = page
        self._last_request_receipt = receipt
        return page

    def generate(self, prompt, image_path=None, progress=None):
        self._last_request_receipt = None
        result = self._generate_page(prompt, image_path, progress)
        if self._last_request_receipt:
            result['cleanup_receipt'] = self._last_request_receipt
        return result

    def _generate_page(self, prompt: str, image_path: Path | None = None, progress=None) -> dict[str, Any]:
        from playwright.sync_api import Error, TimeoutError as PlaywrightTimeout
        progress = progress or (lambda stage: None)
        progress('正在连接 Gemini 网页')
        stage = '连接专用浏览器'
        if not self._listening():
            progress('正在打开 Gemini 窗口，复用原登录配置')
            launched = self.start_browser()
            if launched['status'] != 'window_opened':
                return launched
        try:
            with self._connection(wake=True) as browser:
                if not browser.contexts:
                    return {"status": "unavailable", "detail": "Gemini browser has no usable context"}
                stage = '新建 Gemini 标签页'
                progress(stage)
                page = self._new_task_page(browser)
                page.set_default_timeout(3000)
                stage = '加载 Gemini 页面'
                progress(stage)
                page.goto(GEMINI_URL, wait_until="domcontentloaded", timeout=30000)
                page.bring_to_front()
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    state = self._page_state(page)
                    if state["status"] in {"ready", "login_required", "human_required", "rate_limited"}:
                        break
                    page.wait_for_timeout(250)
                if state["status"] != "ready":
                    return state
                if hasattr(progress, 'bind_page'):
                    progress.bind_page(page)
                # A fresh /app tab prevents old conversation answers becoming this result.
                previous_response_count = page.locator("model-response").count()
                if image_path:
                    is_pdf = image_path.suffix.lower() == '.pdf'
                    progress('正在上传原PDF至 Gemini' if is_pdf else '正在上传图片至 Gemini')
                    inputs = page.locator('input[type="file"]')
                    if not inputs.count():
                        attach = self._visible(page.get_by_role('button', name=re.compile(r'Add files|Upload files|上传和工具|添加文件|上传文件|新增檔案', re.I)))
                        if attach is None:
                            return {"status": "error", "detail": "Gemini image upload control was not found; no prompt was sent"}
                        attach.press('Enter')
                        menu = page.get_by_role('menuitem', name=re.compile(r'Upload|上传|上傳', re.I)).first
                        try:
                            menu.wait_for(state='visible', timeout=5000)
                        except PlaywrightTimeout:
                            # During initial hydration the control can be visible
                            # before its event handler is ready. Never toggle an open menu.
                            if attach.get_attribute('aria-expanded') != 'false':
                                raise
                            attach.press('Enter')
                            menu.wait_for(state='visible', timeout=5000)
                    if inputs.count():
                        image_input = page.locator('input[type="file"]:not([accept]), input[type="file"][accept=""], input[type="file"][accept*="pdf"], input[type="file"][accept="*"]') if is_pdf else page.locator('input[type="file"][accept*="image"]')
                        if is_pdf and not image_input.count():
                            return {"status":"error", "detail":"未找到支持PDF的上传控件；未发送题目"}
                        (image_input.first if image_input.count() else inputs.first).set_input_files(str(image_path))
                    else:
                        upload = self._visible(page.get_by_role('menuitem', name=re.compile(r'Upload|上传|上傳', re.I)))
                        upload = upload or self._visible(page.get_by_role('button', name=re.compile(r'Upload files|上传文件|上傳檔案', re.I)))
                        if upload is None:
                            return {"status": "error", "detail": "Gemini file picker was not found; no prompt was sent"}
                        progress('等待 Gemini 文件选择器')
                        with page.expect_file_chooser(timeout=10000) as chooser:
                            upload.press('Enter')
                        chooser.value.set_files(str(image_path))
                editor = self._editor(page)
                stage = '填写题目'
                editor.fill(prompt)
                if image_path:
                    progress('等待 Gemini PDF附件就绪' if is_pdf else '等待 Gemini 图片附件就绪')
                    ready = self._await_pdf_ready(page, image_path.name) if is_pdf else self._await_image_ready(page)
                    if not ready:
                        return {"status": "timeout", "detail": "附件尚未确认上传完成，未发送题目；请检查 Gemini 窗口"}
                send = self._visible(page.get_by_role("button", name=re.compile(r"^(Send|Send message|Submit|发送|提交|傳送)(訊息|消息)?$", re.I)))
                if image_path and send is None:
                    send = page.get_by_role('button', name=re.compile(r'^(Send|Send message|Submit|发送|提交|傳送)(訊息|消息)?$', re.I)).first
                    send.wait_for(state='visible', timeout=60000)
                stage = '提交题目（若超时，先检查原页面，勿重复提交）'
                if hasattr(progress, 'before_send'):
                    progress.before_send(page)
                page.bring_to_front()
                previous_queries = page.locator('user-query').count()
                if send is not None and image_path:
                    from playwright.sync_api import expect
                    expect(send).to_be_enabled(timeout=60000)
                self._submit_once(editor, send)
                stage = '确认网页已接收题目（未确认时不会自动重发）'
                page.wait_for_function("""counts =>
                    document.querySelectorAll('model-response').length > counts.responses ||
                    (document.querySelectorAll('user-query').length > counts.queries &&
                    [...document.querySelectorAll('[contenteditable="true"]')].every(e => !e.textContent.trim()))
                """, arg={'responses':previous_response_count,'queries':previous_queries}, timeout=15000)
                if hasattr(progress, 'after_send'):
                    progress.after_send(page)
                progress('已发送，等待 AI 回复完毕')
                stage = '等待 Gemini 回复'
                result = self._await_response(page, previous_response_count, progress=progress)
                return result
        except PlaywrightTimeout:
            return {"status": "timeout", "detail": f"Gemini 网页超时：{stage}；请检查专用浏览器，未自动重发"}
        except BrowserUnavailable:
            return {"status": "unavailable", "detail": f"Gemini 浏览器连接未完成：{stage}；这不表示账号未登录"}
        except Error:
            return {"status": "error", "detail": "Gemini page interaction failed; inspect the dedicated browser"}

    @staticmethod
    def _submit_once(editor, send):
        # Some Gemini button variants do not dispatch click on Enter. An uncertain
        # pointer activation must propagate; never submit a second time as fallback.
        if send is None:
            editor.press('Enter')
        else:
            send.click(timeout=10000)

    def _await_pdf_ready(self, page, filename, timeout_seconds: float = 60) -> bool:
        deadline = time.monotonic() + timeout_seconds
        ready_since = None
        while time.monotonic() < deadline:
            ready = page.locator('.text-input-field').evaluate_all(r"""(fields, filename) => fields.some(field => {
                const visible = e => !!e && e.getClientRects().length > 0;
                const previews = [...field.querySelectorAll('uploader-file-preview')];
                const stem = filename.replace(/\.pdf$/i, '');
                const shortName = stem.slice(0,10) + '...' + stem.slice(-10);
                const preview = previews.find(p => visible(p) &&
                    (p.textContent.includes(filename) || (p.querySelector('.gem-attachment-extension-label')?.textContent.trim()==='PDF' && p.querySelector('.gem-attachment-text')?.textContent.trim()===shortName) || [...p.querySelectorAll('[title], [aria-label]')].some(
                        e => (e.getAttribute('title') || e.getAttribute('aria-label') || '').includes(filename))));
                const send = field.querySelector('[data-test-id="send-button-container"] button');
                const busy = [...field.querySelectorAll('[role="progressbar"], [aria-busy="true"], mat-spinner, mat-progress-spinner')].some(visible);
                return !!preview && !busy && visible(send) && !send.disabled && !send.closest('[aria-disabled="true"]');
            })""", filename)
            if ready:
                if ready_since is None:
                    ready_since = time.monotonic()
                if time.monotonic() - ready_since >= 1:
                    return True
            else:
                ready_since = None
            page.wait_for_timeout(250)
        return False

    def _await_image_ready(self, page, timeout_seconds: float = 60) -> bool:
        deadline = time.monotonic() + timeout_seconds
        ready_since = None
        while time.monotonic() < deadline:
            # The preview can appear before the upload finishes. Gemini also
            # disables the send button's custom-element ancestor while uploading.
            ready = page.locator('.text-input-field').evaluate_all("""fields => fields.some(field => {
                const preview = field.querySelector('uploader-file-preview');
                const image = preview?.querySelector('img');
                const send = field.querySelector('[data-test-id="send-button-container"] button');
                const visible = e => !!e && e.getClientRects().length > 0;
                const busy = preview && [...preview.querySelectorAll(
                    '[role="progressbar"], [aria-busy="true"], mat-spinner, mat-progress-spinner'
                )].some(visible);
                return visible(preview) && image?.complete && image.naturalWidth > 0 && !busy
                    && visible(send) && !send.disabled && !send.closest('[aria-disabled="true"]');
            })""")
            if ready:
                if ready_since is None:
                    ready_since = time.monotonic()
                if time.monotonic() - ready_since >= 1:
                    return True
            else:
                ready_since = None
            page.wait_for_timeout(250)
        return False

    def _await_response(self, page, previous_response_count: int = 0, progress=None) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout_seconds
        stable = FinalResponseTracker()
        partial = ""
        while time.monotonic() < deadline:
            if hasattr(progress, 'check'):
                progress.check(page)
            state = self._page_state(page)
            if state["status"] in {"login_required", "human_required", "rate_limited"}:
                return state
            blocks = page.locator("model-response")
            if blocks.count() > previous_response_count:
                block = blocks.last
                content = block.locator("message-content .markdown, .model-response-text .markdown, message-content")
                if content.count():
                    partial = content.first.inner_text().strip()
                # Finished answers expose response actions. Stable text alone is not completion.
                actions = self._visible(block.get_by_role("button", name=re.compile(r"copy|复制|複製|good response|bad response|回答得好|回答得不好", re.I)))
                stop = self._visible(page.get_by_role("button", name=re.compile(r"stop response|stop generating|停止回答|停止生成", re.I)))
                if stable.observe(partial, actions is not None, stop is not None, time.monotonic()):
                    if hasattr(progress, 'check'):
                        progress.check(page)
                    return {"status": "completed", "text": partial, "conversation_url": page.url,
                            "model": "Gemini Web (website-selected model)", "detail": "Response completion controls detected"}
            page.wait_for_timeout(500)
        return {"status": "timeout", "text": "", "partial_text": partial,
                "conversation_url": page.url, "detail": "No confirmed final Gemini response before timeout; partial text is not a completed answer"}


class BrowserUnavailable(Exception):
    pass


class FinalResponseTracker:
    def __init__(self, stable_seconds: float = 1.5):
        self.stable_seconds = stable_seconds
        self._text = ""
        self._since = 0.0

    def observe(self, text: str, has_final_actions: bool, is_generating: bool, now: float) -> bool:
        if not text or text != self._text or not has_final_actions or is_generating:
            self._text, self._since = text, now
            return False
        return now - self._since >= self.stable_seconds

