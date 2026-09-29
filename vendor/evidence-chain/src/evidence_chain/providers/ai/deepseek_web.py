"""Visible DeepSeek website calls with a dedicated persistent login profile."""

from pathlib import Path
import os
import re
import time
from urllib.parse import urlparse
from uuid import uuid4

from evidence_chain.providers.ai.gemini_web import (
    GeminiWebProvider, GeminiBrowserTransport, FinalResponseTracker, BrowserUnavailable,
)

DEEPSEEK_URL = 'https://chat.deepseek.com/'


class DeepSeekWebProvider(GeminiWebProvider):
    provider_id = 'deepseek_web'
    supports_attachments = True

    def __init__(self, *, transport=None, timeout_seconds=180):
        endpoint=os.environ.get('EVIDENCE_CHAIN_DEEPSEEK_CDP_URL','http://127.0.0.1:9231')
        profile=Path(__file__).resolve().parents[4]/'.runtime'/'deepseek-browser'
        super().__init__(endpoint, timeout_seconds=timeout_seconds, profile_dir=profile,
            transport=transport or DeepSeekBrowserTransport(endpoint,profile,timeout_seconds))


class DeepSeekBrowserTransport(GeminiBrowserTransport):
    home_url = DEEPSEEK_URL

    def start_browser(self):
        result=super().start_browser()
        result.update(url=self.home_url)
        result['detail']=result.get('detail','').replace('Gemini','DeepSeek')
        return result

    def _editor(self,page):
        return self._visible(page.locator('textarea'))

    def _page_state(self,page):
        if urlparse(page.url).hostname!='chat.deepseek.com':
            return dict(status='unavailable',detail='请在专用窗口打开 DeepSeek',url=page.url)
        if '/sign_in' in page.url or self._visible(page.get_by_role('button',name=re.compile(r'^(登录|Log in|Sign in)$',re.I))):
            return dict(status='login_required',detail='请在 DeepSeek 专用窗口登录，登录状态保留在本机',url=page.url)
        if self._visible(page.locator('iframe[src*="challenge"], iframe[src*="captcha"], [role="dialog"]').filter(has_text=re.compile('验证|verification',re.I))):
            return dict(status='human_required',detail='请在 DeepSeek 窗口完成人工验证',url=page.url)
        return dict(status='ready' if self._editor(page) else 'unavailable',url=page.url,
            detail='DeepSeek 网页已就绪' if self._editor(page) else 'DeepSeek 页面尚未就绪')

    def status(self):
        from playwright.sync_api import Error
        if not self._listening():return dict(status='unavailable',detail='尚未打开 DeepSeek 专用窗口')
        try:
            with self._connection() as browser:
                pages=[p for c in browser.contexts for p in c.pages if urlparse(p.url).hostname=='chat.deepseek.com']
                for page in reversed(pages):
                    state=self._page_state(page)
                    if state['status']=='ready':return state
                return self._page_state(pages[-1]) if pages else dict(status='unavailable',detail='请打开 DeepSeek 窗口')
        except (Error,BrowserUnavailable):
            return dict(status='unavailable',detail='DeepSeek 浏览器连接失败；不表示账号未登录')

    @staticmethod
    def _composer_image_ready(editor):
        # Image cards may contain a thumbnail with no filename text.
        return editor.evaluate("""editor => {
            let area = editor.parentElement;
            for (let level=0; area && area!==document.body && level<6; level++,area=area.parentElement) {
                if ([...area.querySelectorAll('img')].some(img =>
                    img.getClientRects().length && img.complete && img.naturalWidth>0 &&
                    !/avatar|logo|头像/i.test(img.alt || '') &&
                    (img.src.startsWith('blob:') || img.src.startsWith('data:image/') ||
                     img.width>=40 && img.height>=40))) return true;
            }
            return false;
        }""")

    def _generate_page(self,prompt,image_path=None,progress=None):
        from playwright.sync_api import Error, TimeoutError
        progress=progress or (lambda message:None)
        if not self._listening():
            launched=self.start_browser()
            if launched['status']!='window_opened':return launched
        try:
            with self._connection() as browser:
                if not browser.contexts:return dict(status='unavailable',detail='DeepSeek 浏览器无可用会话')
                page=self._new_task_page(browser)
                page.set_default_timeout(4000)
                progress('正在加载 DeepSeek 新会话')
                page.goto(self.home_url,wait_until='domcontentloaded',timeout=30000)
                page.bring_to_front()
                deadline=time.monotonic()+20
                while time.monotonic()<deadline:
                    state=self._page_state(page)
                    if state['status'] in {'ready','login_required','human_required'}:break
                    page.wait_for_timeout(250)
                if state['status']!='ready':return state
                if page.locator('.ds-markdown').count():
                    return dict(status='error',detail='新会话含旧回答，未发送；请检查 DeepSeek 窗口')
                if image_path:
                    progress('正在上传题目图片至 DeepSeek')
                    inputs = page.locator('input[type="file"]')
                    if not inputs.count():
                        attach = self._visible(page.get_by_role('button', name=re.compile('上传|附件|添加文件|Upload|Attach',re.I)))
                        if attach is None:
                            return dict(status='unsupported',detail='当前DeepSeek页面未找到图片上传控件，未发送题目；可在普通Edge手动上传后导入回答')
                        attach.click()
                    if not inputs.count():
                        return dict(status='unsupported',detail='DeepSeek图片选择控件未就绪，未发送题目')
                    inputs.first.set_input_files(str(image_path))
                    deadline = time.monotonic()+60
                    ready_since = None
                    while time.monotonic()<deadline:
                        failed=self._visible(page.get_by_text(re.compile('上传失败|解析失败|Upload failed',re.I)))
                        if failed:
                            return dict(status='error',detail='DeepSeek图片上传或解析失败，未发送题目')
                        preview=self._visible(page.get_by_text(image_path.stem,exact=False))
                        thumbnail=self._composer_image_ready(self._editor(page))
                        busy=self._visible(page.locator('[role="progressbar"], [aria-busy="true"]'))
                        processing=self._visible(page.get_by_text(re.compile('正在上传|正在解析|Uploading|Processing',re.I)))
                        ready=(preview is not None or thumbnail) and busy is None and processing is None
                        if ready:
                            if ready_since is None:ready_since=time.monotonic()
                            if time.monotonic()-ready_since>=1.5:break
                        else:ready_since=None
                        page.wait_for_timeout(250)
                    else:
                        return dict(status='timeout',detail='DeepSeek图片未确认上传完成，未发送题目；请检查原窗口')
                editor=self._editor(page)
                editor.fill(prompt)
                editor.press('Enter')
                progress('DeepSeek 已发送，等待完整回答')
                tracker=FinalResponseTracker(2)
                deadline=time.monotonic()+self.timeout_seconds
                while time.monotonic()<deadline:
                    state=self._page_state(page)
                    if state['status'] in {'login_required','human_required'}:return state
                    blocks=page.locator('.ds-markdown')
                    text=blocks.last.inner_text().strip() if blocks.count() else ''
                    stop=self._visible(page.get_by_role('button',name=re.compile('停止|Stop',re.I)))
                    actions=(self._visible(blocks.last.locator('..').locator('..').get_by_role('button',name=re.compile('^(朗读|Read aloud)$',re.I)))
                        if blocks.count() else None)
                    if tracker.observe(text,actions is not None,stop is not None,time.monotonic()):
                        return dict(status='completed',text=text,conversation_url=page.url,
                            model='DeepSeek Web (website-selected model)')
                    page.wait_for_timeout(500)
                return dict(status='timeout',detail='DeepSeek 未确认完整回复；保留页面，未自动重发')
        except (TimeoutError,Error,BrowserUnavailable):
            return dict(status='error',detail='DeepSeek 网页操作未完成；请检查原窗口，未自动重发')
