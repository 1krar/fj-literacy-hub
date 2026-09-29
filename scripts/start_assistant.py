"""Start/reuse the local helper and open it in the user's normal Edge profile."""
from pathlib import Path
from urllib.request import build_opener, ProxyHandler
import argparse
import importlib.util
import os
import subprocess
import sys
import time
import webbrowser
import html
from contextlib import contextmanager
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
URL = 'http://127.0.0.1:8771/assistant.html'


def running():
    try:
        with build_opener(ProxyHandler({})).open(URL, timeout=1) as response:
            return response.headers.get('X-Literacy-Assistant') == '1'
    except OSError:
        return False


def validate_protocol(value):
    if not value:
        return
    parsed=urlsplit(value)
    if (parsed.scheme!='literacy-assistant' or parsed.netloc!='open' or parsed.path not in ('','/')
            or parsed.query or parsed.fragment or any(c in value for c in '\"\r\n')):
        raise ValueError('无效的助手启动地址')


def ensure_environment():
    default_root=ROOT.parent/'evidence-chain'
    if not (default_root/'src/evidence_chain/providers/ai/gemini_web.py').is_file():
        default_root=ROOT/'vendor/evidence-chain'
    provider_root=Path(os.environ.get('EVIDENCE_CHAIN_ROOT',default_root))
    for name in ('gemini','deepseek'):
        if not (provider_root/'src/evidence_chain/providers/ai'/f'{name}_web.py').is_file():
            raise RuntimeError('缺少模型连接组件，请保留项目旁的evidence-chain目录')
    if importlib.util.find_spec('playwright') is None:
        completed=subprocess.run([sys.executable,'-m','pip','install','playwright'],
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if completed.returncode:
            raise RuntimeError('浏览器依赖安装失败，请检查网络后再次启动助手')
        importlib.invalidate_caches()


@contextmanager
def startup_lock():
    import msvcrt
    runtime=ROOT/'.runtime';runtime.mkdir(exist_ok=True)
    with (runtime/'startup.lock').open('a+b') as lock:
        lock.seek(0);lock.write(b'0');lock.flush()
        deadline=time.monotonic()+60
        while True:
            try:
                lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1);break
            except OSError:
                if time.monotonic()>deadline:raise RuntimeError('另一启动过程尚未结束，请稍后再试')
                time.sleep(.2)
        try:yield
        finally:
            lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)


def open_edge(url):
    candidates=[Path(os.environ.get(key,''))/'Microsoft/Edge/Application/msedge.exe' for key in ('PROGRAMFILES(X86)','PROGRAMFILES','LOCALAPPDATA')]
    edge=next((p for p in candidates if p.is_file()),None)
    if edge:subprocess.Popen([str(edge),url])
    else:webbrowser.open(url)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--protocol')
    args=parser.parse_args()
    validate_protocol(args.protocol)
    with startup_lock():
        if not running():
            ensure_environment()
            runtime=ROOT/'.runtime'
            env=dict(os.environ,PYTHONUTF8='1')
            with (runtime/'assistant.stdout.log').open('ab') as out,(runtime/'assistant.stderr.log').open('ab') as err:
                process=subprocess.Popen([sys.executable,'-B',str(ROOT/'scripts/assistant_server.py')],cwd=ROOT,
                    stdout=out,stderr=err,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            (runtime/'assistant.pid').write_text(str(process.pid))
            for _ in range(125):
                if running():break
                if process.poll() is not None:raise RuntimeError('本机服务启动失败；可能端口被其他程序占用，请检查后台日志')
                time.sleep(.2)
            else:raise RuntimeError('本机服务启动超时，请稍后再次点击入口')
    if sys.stdout:print('比赛助手已运行：'+URL)
    # The web launch page owns its new tab and redirects when ready.
    # Opening Edge here as well would create a second assistant tab.
    if not args.no_browser and not args.protocol:
        open_edge(URL)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        if sys.stderr:print(str(error),file=sys.stderr)
        else:
            runtime=ROOT/'.runtime';runtime.mkdir(exist_ok=True)
            report=runtime/'startup-error.html'
            report.write_text('<meta charset="utf-8"><title>助手启动提示</title><h1>本机助手暂未启动</h1><p>'+html.escape(str(error))+'</p><p>处理后返回素养聚合，再点击题目路线助手即可。</p>',encoding='utf-8')
            open_edge(report.as_uri())
        sys.exit(1)
