"""Register a current-user launcher; no browser security policy changes."""
from pathlib import Path
import sys
import winreg
from start_assistant import ensure_environment

ROOT=Path(__file__).resolve().parents[1]
def main():
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
    print('本机一键启动入口已安装：literacy-assistant://open')
if __name__=='__main__':main()
