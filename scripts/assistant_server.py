"""Loopback-only bridge to the existing Gemini/DeepSeek website providers; no cookies exported."""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
import argparse
import base64
import hmac
import importlib.util
import json
import os
import secrets
import sys
import types
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
MAX_IMAGE = 5 * 1024 * 1024
if str(ROOT / 'scripts') not in sys.path:
    sys.path.insert(0, str(ROOT / 'scripts'))
from ctrl_multi import MultiCtrlJobs


def read_input(data):
    if not isinstance(data, dict):
        raise ValueError('需要题目参数对象')
    question, prompt = data.get('question'), data.get('prompt')
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= 10000:
        raise ValueError('题目应为1至10000字符')
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 24000:
        raise ValueError('拆题请求超过24000字符，请缩短题目')
    image = data.get('image')
    if image is None:
        return prompt, None, None
    if not isinstance(image, str) or len(image) > 7_000_000:
        raise ValueError('截图过大')
    prefix, _, encoded = image.partition(',')
    if prefix not in ('data:image/png;base64', 'data:image/jpeg;base64'):
        raise ValueError('只支持PNG或JPEG截图')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise ValueError('截图编码不正确') from exc
    valid = (prefix.endswith('png;base64') and raw.startswith(b'\x89PNG\r\n\x1a\n')) or (prefix.endswith('jpeg;base64') and raw.startswith(b'\xff\xd8\xff'))
    if not valid or len(raw) > MAX_IMAGE:
        raise ValueError('截图格式不正确或超过5MB')
    return prompt, raw, '.png' if 'png' in prefix else '.jpg'


def load_provider(evidence_root):
    # Namespace packages avoid importing the unrelated evidence pipeline.
    # Use the bundled, tested adapters while retaining the existing browser
    # profiles under evidence_root, so current Edge logins are reused.
    bundled = ROOT / 'vendor/evidence-chain/src/evidence_chain/providers/ai'
    ai = bundled if bundled.is_dir() else evidence_root / 'src/evidence_chain/providers/ai'
    for name, folder in [('evidence_chain', ai.parents[1]), ('evidence_chain.providers', ai.parent), ('evidence_chain.providers.ai', ai)]:
        if name not in sys.modules:
            package = types.ModuleType(name)
            package.__path__ = [str(folder)]
            sys.modules[name] = package
    loaded = {}
    for name, cls in [('gemini', 'GeminiWebProvider'), ('deepseek', 'DeepSeekWebProvider')]:
        path = ai / (name + '_web.py')
        if not path.is_file():
            raise ValueError('未找到 ' + name + ' Provider，请检查 EVIDENCE_CHAIN_ROOT')
        module_name = 'evidence_chain.providers.ai.' + name + '_web'
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        if name == 'gemini':
            loaded[name] = getattr(module, cls)(profile_dir=evidence_root / '.runtime/gemini-browser')
        else:
            endpoint = os.environ.get('EVIDENCE_CHAIN_DEEPSEEK_CDP_URL', 'http://127.0.0.1:9231')
            transport = module.DeepSeekBrowserTransport(endpoint, evidence_root / '.runtime/deepseek-browser', 180)
            loaded[name] = getattr(module, cls)(transport=transport)
    return loaded


def selected_models(data):
    names = data.get('models', ['deepseek'])
    if not isinstance(names, list) or not names or len(names) > 2 or len(set(names)) != len(names) or any(n not in ('gemini', 'deepseek') for n in names):
        raise ValueError('请选择 Gemini、DeepSeek 或两者')
    return names


class Jobs:
    def __init__(self, provider):
        self.providers = provider if isinstance(provider, dict) else {'gemini': provider}
        self.provider = self.providers['gemini']
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.lock = threading.Lock()
        self.items = {}
        self.active = None
        self.retained_receipts = {}

    def submit(self, data):
        prompt, raw, suffix = read_input(data)
        names = selected_models(data)
        if any(n not in self.providers for n in names):
            raise ValueError('当前服务尚未配置所选模型')
        with self.lock:
            if self.active:
                raise RuntimeError('本助手已有一道题正在分析，请等待完成')
            if len(self.items) >= 20:
                del self.items[next(iter(self.items))]
            job_id = uuid.uuid4().hex
            self.active = job_id
            self.items[job_id] = dict(id=job_id, state='running', stage='正在连接所选模型网页', models=names, results={}, progress={n:dict(state='running',stage='准备连接') for n in names}, started_at=time.time())
        self.pool.submit(self.run, job_id, prompt, raw, suffix, names)
        return {'id': job_id}

    def get(self, job_id):
        with self.lock:
            return json.loads(json.dumps(self.items[job_id]))

    def run(self, job_id, prompt, raw, suffix, names):
        path = None
        def call(name, request, attachment):
            def progress(stage):
                with self.lock:
                    self.items[job_id]['stage'] = name + ' · ' + stage
                    self.items[job_id]['progress'][name]['stage'] = stage
            cleanup = getattr(self.providers[name], 'close_saved_response', None)
            previous = self.retained_receipts.pop(name, None)
            if previous and cleanup:
                try: cleanup(previous)
                except Exception: pass  # Cleanup must never discard an AI result.
            result = {}
            try:
                result = self.providers[name].generate_with_progress(request, attachment, progress)
                if result.get('status') == 'completed' and result.get('text', '').strip():
                    value = dict(state='completed', text=result['text'])
                else:
                    value = dict(state='failed', error=result.get('detail') or result.get('status') or '未返回完整回答')
            except Exception as exc:
                value = dict(state='failed', error=f'{name}调用异常（{type(exc).__name__}），请检查原窗口')
            with self.lock:
                value['completed_at'] = time.time()
                self.items[job_id]['results'][name] = value
                self.items[job_id]['progress'][name] = dict(state=value['state'],stage='路线回答完成' if value['state']=='completed' else value['error'])
            receipt = result.get('cleanup_receipt')
            if receipt and cleanup:
                if value['state'] == 'completed':
                    try: cleanup_status = cleanup(receipt).get('status', 'retained')
                    except Exception: cleanup_status = 'retained'
                    if cleanup_status not in ('closed', 'not_owned', 'changed'):
                        self.retained_receipts[name] = receipt
                    with self.lock:
                        self.items[job_id]['results'][name]['tab_cleanup'] = cleanup_status
                else:
                    # Retain one failed task for inspection, close it on next call.
                    self.retained_receipts[name] = receipt
            return value
        try:
            if raw:
                folder = ROOT / '.runtime/uploads'
                folder.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=folder, suffix=suffix, delete=False) as image:
                    image.write(raw)
                    path = Path(image.name)
            with ThreadPoolExecutor(max_workers=len(names)) as models_pool:
                list(models_pool.map(lambda name: call(name, prompt, path), names))
            with self.lock:
                results = self.items[job_id]['results']
                successful = [v for v in results.values() if v['state'] == 'completed']
                if successful:
                    self.items[job_id].update(state='completed', stage='所选模型已完成处理', text=successful[0]['text'])
                else:
                    self.items[job_id].update(state='failed', error='；'.join(n + ': ' + v['error'] for n, v in results.items()))
        except Exception as exc:
            with self.lock:
                self.items[job_id].update(state='failed', error=f'本机任务异常（{type(exc).__name__}），未自动重发')
        finally:
            if path:
                path.unlink(missing_ok=True)
            with self.lock:
                self.active = None


def handler_for(jobs, session, ctrl_jobs=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log questions, images, session tokens or model responses.

        def reply(self, status, value, mime='application/json; charset=utf-8', launch_origin=False):
            raw = json.dumps(value, ensure_ascii=False).encode() if mime.startswith('application/json') else value
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Literacy-Assistant', '1')
            if launch_origin:
                self.send_header('Access-Control-Allow-Origin', 'https://fj-literacy-hub.pages.dev')
                self.send_header('Vary', 'Origin')
                self.send_header('Access-Control-Allow-Methods', 'GET')
                self.send_header('Access-Control-Allow-Private-Network', 'true')
            self.end_headers()
            self.wfile.write(raw)

        def allowed(self):
            expected = f'127.0.0.1:{self.server.server_port}'
            return (self.headers.get('Host') == expected and
                    self.headers.get('Origin', 'http://' + expected) == 'http://' + expected and
                    self.headers.get('Sec-Fetch-Site', 'same-origin') not in ('cross-site', 'same-site'))

        def launch_probe_allowed(self):
            return (self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}' and
                    self.headers.get('Origin') == 'https://fj-literacy-hub.pages.dev')

        def do_OPTIONS(self):
            if (self.path == '/api/launch-status' and self.launch_probe_allowed() and
                    self.headers.get('Access-Control-Request-Method') == 'GET' and
                    not self.headers.get('Access-Control-Request-Headers')):
                self.reply(200, {}, launch_origin=True)
            else:
                self.reply(403, {'error': '不允许此跨域请求'})

        def do_GET(self):
            path = urlsplit(self.path).path
            # Readiness only: no session, login state, questions or model controls.
            if path == '/api/launch-status' and self.launch_probe_allowed():
                self.reply(200, {'app': 'literacy-assistant', 'ready': True}, launch_origin=True)
                return
            navigation = (not path.startswith('/api/') and
                          self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}' and
                          self.headers.get('Sec-Fetch-Mode') == 'navigate')
            if not self.allowed() and not navigation:
                self.reply(403, {'error': '仅允许本机同源访问'})
                return
            if path == '/api/launch-status':
                self.reply(200, {'app': 'literacy-assistant', 'ready': True})
            elif path == '/api/session':
                self.reply(200, {'session': session})
            elif path.startswith('/api/'):
                if not hmac.compare_digest(self.headers.get('X-Assistant-Session', ''), session):
                    self.reply(403, {'error': '请刷新本机助手页面'})
                    return
                if path == '/api/status':
                    name = urlsplit(self.path).query.removeprefix('model=') or 'gemini'
                    if name not in jobs.providers:
                        self.reply(400, {'error': '未知模型'})
                    else:
                        self.reply(200, jobs.providers[name].status())
                elif path == '/api/ctrl/session' and ctrl_jobs:
                    try:
                        session_id = urlsplit(self.path).query.removeprefix('id=')
                        self.reply(200, ctrl_jobs.get_session(session_id))
                    except KeyError:
                        self.reply(404, {'error': 'CTRL 会话已过期，请重新提交题目'})
                elif path.startswith('/api/jobs/'):
                    try:
                        self.reply(200, jobs.get(path.rsplit('/', 1)[-1]))
                    except KeyError:
                        self.reply(404, {'error': '本次任务已过期，请检查Gemini原会话'})
                else:
                    self.reply(404, {'error': '未找到接口'})
            else:
                name = 'assistant.html' if path == '/' else path.lstrip('/')
                # A flat static allow-list; never serve the source tree/runtime/provider profile.
                types = {'.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8', '.txt': 'text/plain; charset=utf-8'}
                file = ROOT / 'dist' / name
                if '/' in name or '\\' in name or '..' in name or file.suffix not in types or not file.is_file():
                    self.reply(404, {'error': '未找到页面'})
                else:
                    self.reply(200, file.read_bytes(), types[file.suffix])

        def do_POST(self):
            if not self.allowed() or not hmac.compare_digest(self.headers.get('X-Assistant-Session', ''), session):
                self.reply(403, {'error': '请从本机助手页面发起调用'})
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 7_200_000:
                    raise ValueError('请求过大或为空')
                data = json.loads(self.rfile.read(size))
                if self.path == '/api/jobs':
                    self.reply(202, jobs.submit(data))
                elif self.path == '/api/ctrl/start' and ctrl_jobs:
                    self.reply(202, ctrl_jobs.start(data))
                elif self.path == '/api/ctrl/answer' and ctrl_jobs:
                    self.reply(202, ctrl_jobs.answer(data))
                elif self.path == '/api/ctrl/retry' and ctrl_jobs:
                    self.reply(202, ctrl_jobs.retry(data))
                elif self.path == '/api/browser/open':
                    name = data.get('model', 'gemini')
                    if name not in jobs.providers:
                        raise ValueError('未知模型')
                    self.reply(200, jobs.providers[name].start_browser())
                else:
                    self.reply(404, {'error': '未找到接口'})
            except (ValueError, TypeError) as exc:
                self.reply(400, {'error': str(exc)})
            except RuntimeError as exc:
                self.reply(409, {'error': str(exc)})
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8771)
    args = parser.parse_args()
    default_root = ROOT.parent / 'evidence-chain'
    if not (default_root / 'src/evidence_chain/providers/ai/gemini_web.py').is_file():
        default_root = ROOT / 'vendor/evidence-chain'
    root = Path(os.environ.get('EVIDENCE_CHAIN_ROOT', default_root))
    jobs = Jobs(load_provider(root))
    ctrl_jobs = MultiCtrlJobs(jobs, read_input)
    class Server(ThreadingHTTPServer):
        allow_reuse_address = False
        daemon_threads = True
    server = Server(('127.0.0.1', args.port), handler_for(jobs, secrets.token_urlsafe(32), ctrl_jobs))
    print(f'比赛助手就绪：http://127.0.0.1:{args.port}/assistant.html', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        jobs.pool.shutdown(wait=False, cancel_futures=True)


if __name__ == '__main__':
    main()

