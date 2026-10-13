"""Embedded Python 3.8 launcher: API only, no Tk/Playwright installation."""
import argparse
import html
import sys
from pathlib import Path
from app_paths import ROOT

def main():
    import start_assistant
    parser=argparse.ArgumentParser()
    parser.add_argument('--diagnose',action='store_true')
    args=parser.parse_args()
    saved=sys.argv
    try:
        sys.argv=['start','--no-browser']
        start_assistant.main()
    finally:
        sys.argv=saved
    start_assistant.open_edge('http://127.0.0.1:8771/'+
                             ('windows7-diagnostics.html' if args.diagnose else 'ctrl-assistant.html'))

if __name__=='__main__':
    try:main()
    except Exception as error:
        runtime=ROOT/'.runtime';runtime.mkdir(exist_ok=True)
        target=runtime/'win7-startup-error.html'
        target.write_text('<meta charset="utf-8"><title>CTRL 启动失败</title><h1>兼容版暂未启动</h1><p>'+
            html.escape(str(error))+'</p><p>请完整解压运行包，确认 Windows 7 SP1 与系统位数匹配，'
            '目录可写，8771 端口未被其他程序占用。请使用 Edge 109 或相容的 Chromium 浏览器。</p>',encoding='utf-8')
        import start_assistant
        start_assistant.open_edge(target.as_uri())
        print('CTRL startup failed. See the browser message.');sys.exit(1)
