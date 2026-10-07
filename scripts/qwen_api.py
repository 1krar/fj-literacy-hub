"""Local-only Qwen adapter; credentials never returned by the HTTP service."""
import base64
import ctypes
import json
import os
from pathlib import Path
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler
import uuid

DEFAULT_MODEL = 'qwen3.8-flash'


def validate_base(value):
    if not isinstance(value, str) or len(value) > 300:
        raise ValueError('请填写阿里云百炼的 HTTPS Base URL')
    parsed = urlsplit(value)
    hostname = parsed.hostname or ''
    official = hostname in ('dashscope.aliyuncs.com', 'dashscope-intl.aliyuncs.com',
                             'dashscope-us.aliyuncs.com') or hostname.endswith('.maas.aliyuncs.com')
    if (not official or parsed.scheme != 'https' or parsed.username or parsed.password or
            parsed.port not in (None, 443) or parsed.query or parsed.fragment or
            parsed.path.rstrip('/') != '/compatible-mode/v1'):
        raise ValueError('请使用百炼控制台提供的 HTTPS Base URL，路径为 /compatible-mode/v1')
    return value.rstrip('/')


def dpapi(raw, decrypt=False):
    if os.name != 'nt':
        raise ValueError('当前系统不支持 Windows 加密保存；请取消记住配置')
    class Blob(ctypes.Structure):
        _fields_ = [('size', ctypes.c_ulong), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Blob)]
    function.restype = ctypes.c_int
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError('Windows 加密配置失败，请取消记住配置或检查当前用户权限')
    kernel = ctypes.WinDLL('kernel32')
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        # Never forward a credential to a redirected host.
        return None


class QwenProvider:
    def __init__(self, config_path):
        self.path = Path(config_path)
        self.lock = threading.RLock()
        self.config = {'base_url': '', 'model': DEFAULT_MODEL, 'api_key': ''}
        self.chats = {}
        self.remembered = False
        self.load_error = ''
        if self.path.is_file():
            try:
                saved = json.loads(dpapi(self.path.read_bytes(), decrypt=True))
                self._validated(saved)
                self.config = saved
                self.remembered = True
            except Exception:
                self.load_error = '加密配置无法读取，请重新填写 API 配置'
        if os.environ.get('LITERACY_QWEN_API_KEY'):
            try:
                self.config = self._validated({'api_key': os.environ['LITERACY_QWEN_API_KEY'],
                    'base_url': os.environ.get('LITERACY_QWEN_BASE_URL', ''),
                    'model': os.environ.get('LITERACY_QWEN_MODEL', DEFAULT_MODEL)})
            except ValueError:
                self.load_error = '千问环境变量配置无效，请在设置中重新填写'

    def _validated(self, data):
        key = data.get('api_key', '')
        if not isinstance(key, str) or not re.fullmatch(r'[\x21-\x7e]{8,4096}', key):
            raise ValueError('请填写有效 API Key（不能含空格或换行）')
        model = data.get('model', DEFAULT_MODEL)
        if model != DEFAULT_MODEL:
            raise ValueError('此入口当前接入 qwen3.8-flash，其他模型稍后扩展')
        return {'base_url': validate_base(data.get('base_url', '')), 'model': model, 'api_key': key}

    def public_config(self):
        with self.lock:
            return {'base_url': self.config['base_url'], 'model': self.config['model'],
                    'configured': bool(self.config['api_key']), 'remembered': self.remembered,
                    'detail': self.load_error}

    def configure(self, data):
        with self.lock:
            value = dict(data)
            if not value.get('api_key'):
                value['api_key'] = self.config['api_key']
            config = self._validated(value)
            remember = data.get('remember', False)
            if not isinstance(remember, bool):
                raise ValueError('记住配置选项无效')
            if remember:
                protected = dpapi(json.dumps(config).encode())
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix('.tmp.dpapi')
                temporary.write_bytes(protected)
                temporary.replace(self.path)
            else:
                self.path.unlink(missing_ok=True)
            self.config, self.remembered, self.load_error = config, remember, ''
            return self.public_config()

    def status(self):
        config = self.public_config()
        return {'status': 'ready' if config['configured'] else 'not_configured',
                'detail': '千问 API 已配置，实际可用性以调用结果为准' if config['configured'] else
                          config['detail'] or '请展开 API 设置填写百炼 API Key 和 Base URL'}

    def generate_with_progress(self, prompt, path, progress):
        receipt = uuid.uuid4().hex
        content = prompt
        if path:
            mime = 'image/png' if path.suffix == '.png' else 'image/jpeg'
            content = [{'type': 'text', 'text': prompt}, {'type': 'image_url', 'image_url': {
                'url': 'data:'+mime+';base64,'+base64.b64encode(path.read_bytes()).decode()}}]
        with self.lock:
            self.chats[receipt] = {'messages': [], 'last': None}
        return self.continue_saved(receipt, content, progress)

    def continue_saved(self, receipt, prompt, progress):
        with self.lock:
            if receipt not in self.chats:
                raise RuntimeError('API 原题上下文已过期，请重新提交题目')
            chat = self.chats[receipt]
            messages = chat['messages'] + [{'role': 'user', 'content': prompt}]
            chat['last'] = None
            config = dict(self.config)
        result = self._request(config, messages, progress)
        result['cleanup_receipt'] = receipt
        with self.lock:
            if result['status'] == 'completed':
                chat['messages'] = messages + [{'role': 'assistant', 'content': result['text']}]
                chat['last'] = result['text']
        return result

    def _request(self, config, messages, progress):
        if not config['api_key']:
            return {'status': 'failed', 'detail': '千问 API 尚未配置'}
        progress('正在发送千问 API 请求')
        body = json.dumps({'model': config['model'], 'messages': messages,
            'enable_thinking': False, 'max_tokens': 4096, 'stream': True}).encode()
        request = Request(config['base_url']+'/chat/completions', data=body,
            headers={'Authorization': 'Bearer '+config['api_key'], 'Content-Type': 'application/json'})
        chunks, finish, received = [], None, False
        deadline = time.monotonic()+150
        try:
            with build_opener(NoRedirect()).open(request, timeout=45) as response:
                for line in response:
                    if time.monotonic() > deadline:
                        return {'status': 'failed', 'detail': 'API 回复超时，尚未确认完整结果；可手动重试'}
                    if not line.startswith(b'data:'):
                        continue
                    raw = line[5:].strip()
                    if raw == b'[DONE]':
                        break
                    item = json.loads(raw)
                    if item.get('error'):
                        return {'status': 'failed', 'detail': 'API 返回错误，请检查模型权限与额度'}
                    choices = item.get('choices') or []
                    if not choices:
                        continue
                    choice = choices[0]
                    value = choice.get('delta', {}).get('content') or ''
                    if value:
                        if not received:
                            progress('正在接收千问 API 回复')
                            received = True
                        chunks.append(value)
                    finish = choice.get('finish_reason') or finish
            if finish != 'stop' or not ''.join(chunks).strip():
                return {'status': 'failed', 'detail': 'API 回复中断或被截断，未采用不完整结果；可手动重试'}
            return {'status': 'completed', 'text': ''.join(chunks)}
        except HTTPError as exc:
            label = {401: 'API Key 无效', 403: '模型或地域权限不足', 429: '请求限流或额度不足'}.get(
                exc.code, '服务暂时无法完成请求')
            return {'status': 'failed', 'detail': f'千问 API {exc.code}：{label}；未自动重发'}
        except (URLError, TimeoutError, OSError, ValueError):
            return {'status': 'failed', 'detail': 'API 网络或响应异常，未确认完整回复；未自动重发，可手动重试'}

    def read_saved_reply(self, receipt):
        with self.lock:
            return self.chats.get(receipt, {}).get('last')

    def close_saved_response(self, receipt):
        with self.lock:
            self.chats.pop(receipt, None)
        return {'status': 'closed'}
