"""Portable, credential-free machine checks. No question or log contents exported."""
from pathlib import Path
import importlib.util
import json
import os
import platform
import socket
import tempfile
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
from app_paths import ROOT

BASE = 'http://127.0.0.1:8771'

def edge_path():
    return next((p for key in ('PROGRAMFILES(X86)', 'PROGRAMFILES', 'LOCALAPPDATA')
                 if (p := Path(os.environ.get(key, ''))/'Microsoft/Edge/Application/msedge.exe').is_file()), None)

def local_json(path, session=None):
    headers = {'X-Assistant-Session': session} if session else {}
    with build_opener(ProxyHandler({})).open(Request(BASE+'/api/'+path, headers=headers), timeout=3) as response:
        if response.headers.get('X-Literacy-Assistant') != '1':
            raise RuntimeError('端口上的服务不是 CTRL 助手')
        return json.load(response)

def diagnose(root=ROOT):
    rows = []
    def add(name, state, detail): rows.append({'name':name,'state':state,'detail':detail})
    add('Windows', '通过' if os.name == 'nt' else '失败', platform.system()+' '+platform.machine())
    missing = [name for name in ('dist/ctrl-assistant.html','dist/resources.json',
               'vendor/evidence-chain/src/evidence_chain/providers/ai/gemini_web.py',
               'vendor/evidence-chain/src/evidence_chain/providers/ai/deepseek_web.py') if not (root/name).is_file()]
    add('运行包文件','失败' if missing else '通过','缺少：'+', '.join(missing) if missing else '文件完整；请保留整个解压目录')
    try:
        folder = root/'.runtime'; folder.mkdir(exist_ok=True)
        with tempfile.TemporaryFile(dir=folder) as file: file.write(b'check')
        add('保存目录','通过','可保存配置及运行日志')
    except OSError:
        add('保存目录','失败','目录不可写；请把整个运行包移到桌面或文档目录，不要在 ZIP 内运行')
    add('Playwright','通过' if importlib.util.find_spec('playwright') else '失败','已包含浏览器连接组件' if importlib.util.find_spec('playwright') else '源码模式请安装依赖；运行包请重新完整解压')
    edge = edge_path()
    add('Microsoft Edge','通过' if edge else '待处理','已找到 Edge' if edge else '未找到 Edge；API 模式可用默认浏览器，网页模型及置顶小窗建议安装 Edge')
    with socket.socket() as connection:
        occupied = connection.connect_ex(('127.0.0.1',8771)) == 0
    try:
        launch = local_json('launch-status')
        if launch.get('app') != 'literacy-assistant': raise ValueError('wrong service')
        add('本机后台','通过','CTRL 助手已启动，可以复用')
        session = local_json('session')['session']
        for name, label in [('qwen','千问 API'),('intern','书生 API')]:
            config = local_json('ctrl/'+name+'-config',session)
            detail = '已配置 '+str(config.get('model','')) if config.get('configured') else '首次在本机 CTRL 设置中填写自己的 API Key'
            if config.get('detail'): detail = config['detail']
            add(label,'通过' if config.get('configured') else '待配置',detail)
    except Exception:
        add('本机后台','失败' if occupied else '未启动','8771 端口被其他程序占用；请关闭占用程序或使用已运行的正确助手' if occupied else '点击“一键启动 CTRL”')
    return rows

def connectivity():
    rows = []
    # Uses normal OS proxy settings. HTTP errors prove the service was reached.
    for label, url in [('千问','https://maas.qianwenaiapi.com/compatible-mode/v1/models'),
                       ('书生','https://discovery-api.intern-ai.org.cn/v1/models')]:
        try:
            with build_opener().open(Request(url),timeout=8) as response:
                rows.append({'name':label+'网络','state':'可达','detail':'HTTP '+str(response.status)+'；尚未验证 Key 或额度'})
        except HTTPError as error:
            rows.append({'name':label+'网络','state':'可达','detail':'HTTP '+str(error.code)+'；需在设置中填写 Key，再实测模型'})
        except Exception:
            rows.append({'name':label+'网络','state':'失败','detail':'连接超时或网络/TLS异常；检查网络及系统代理，再点击网络检查'})
    return rows

def report(rows):
    # Only whitelist diagnostic summaries, never copy environment values, raw logs,
    # cookies, question text, keys, profile paths or arbitrary server errors.
    return 'CTRL 助手启动诊断\n版本：2026-10-12\n'+'\n'.join(
        f"{row['name']} | {row['state']} | {row['detail']}" for row in rows)
