"""Register a current-user launcher; no browser security policy changes."""
from pathlib import Path
import argparse
import sys
import winreg
from start_assistant import ensure_environment

ROOT=Path(__file__).resolve().parents[1]
STARTUP_KEY=r'Software\Microsoft\Windows\CurrentVersion\Run'
STARTUP_NAME='LiteracyHubAssistant'

def set_startup(enabled, interpreter):
    if enabled:
        command=f'"{interpreter}" -B "{ROOT / "scripts/start_assistant.py"}" --no-browser'
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY) as key:
            winreg.SetValueEx(key, STARTUP_NAME, 0, winreg.REG_SZ, command)
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY, 0, winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as key:
                value, _ = winreg.QueryValueEx(key, STARTUP_NAME)
                if 'scripts/start_assistant.py' in value.replace('\\', '/'):
                    winreg.DeleteValue(key, STARTUP_NAME)
        except FileNotFoundError:
            pass

def main():
    parser=argparse.ArgumentParser()
    startup=parser.add_mutually_exclusive_group()
    startup.add_argument('--startup',action='store_true',help='登录 Windows 后在后台启动本机服务')
    startup.add_argument('--no-startup',action='store_true',help='移除本项目的登录启动项')
    args=parser.parse_args()
    ensure_environment()
    interpreter=Path(sys.executable).with_name('pythonw.exe')
    if not interpreter.is_file():raise RuntimeError('未找到pythonw.exe，请使用完整Windows Python环境')
    command=f'"{interpreter}" -B "{ROOT / "scripts/start_assistant.py"}" --protocol "%1"'
    base=r'Software\Classes\literacy-assistant'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,base) as key:
        winreg.SetValueEx(key,'',0,winreg.REG_SZ,'URL:Literacy Assistant')
        winreg.SetValueEx(key,'URL Protocol',0,winreg.REG_SZ,'')
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,base+r'\shell\open\command') as key:
        winreg.SetValueEx(key,'',0,winreg.REG_SZ,command)
    if args.startup or args.no_startup:
        set_startup(args.startup,interpreter)
    print('本机一键启动入口已安装：literacy-assistant://open')
    if args.startup:print('已启用当前用户登录后的后台预启动；不会自动打开网页')
    elif args.no_startup:print('已关闭本项目的登录预启动')
if __name__=='__main__':main()
