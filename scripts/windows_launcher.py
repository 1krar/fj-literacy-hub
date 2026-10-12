"""Windows GUI launcher and frozen backend entry point."""
import argparse
import json
import os
import queue
import sys
import threading
from pathlib import Path
from app_paths import ROOT
from windows_diagnostics import diagnose, connectivity, report, BASE, edge_path

def start_ctrl(open_settings=False):
    import start_assistant
    saved = sys.argv
    try:
        sys.argv = ['launcher','--no-browser']
        start_assistant.main()
    finally:
        sys.argv = saved
    start_assistant.open_edge(BASE+'/ctrl-assistant.html'+('#settings' if open_settings else ''))

def install_entry():
    import install_assistant
    saved = sys.argv
    try:
        sys.argv = ['installer']
        install_assistant.main()
    finally:
        sys.argv = saved

def show_gui(smoke_report=None):
    import tkinter as tk
    from tkinter import ttk
    import start_assistant
    root = tk.Tk(); root.title('CTRL 助手 · 启动与诊断')
    root.geometry('820x530'); root.minsize(700,450)
    main = ttk.Frame(root,padding=20); main.pack(fill='both',expand=True)
    ttk.Label(main,text='在这台电脑启动 CTRL 助手',font=('Microsoft YaHei UI',17,'bold')).pack(anchor='w')
    ttk.Label(main,text='首次填写自己的 API Key；网页模式在助手的模型窗口登录。请先完整解压运行包。').pack(anchor='w',pady=(8,16))
    actions = ttk.Frame(main); actions.pack(fill='x')
    tree = ttk.Treeview(main,columns=('name','state','detail'),show='headings',height=12)
    for key,label,width in [('name','检查项目',125),('state','结果',70),('detail','说明与处理方法',520)]:
        tree.heading(key,text=label);tree.column(key,width=width,minwidth=65,stretch=key=='detail')
    tree.pack(fill='both',expand=True,pady=12)
    status = tk.StringVar(value='正在检查本机环境…')
    ttk.Label(main,textvariable=status,wraplength=760).pack(anchor='w')
    events = queue.Queue(); state={'rows':[],'busy':False}; buttons=[]
    def work(label, action):
        if state['busy']: return
        state['busy']=True; status.set(label+'…')
        for button in buttons: button.configure(state='disabled')
        def run():
            try:
                extra=action() or []
                events.put((True,diagnose()+extra,label+'完成'))
            except Exception as error:
                # Do not display or export subprocess/server responses containing secrets.
                events.put((False,diagnose(),label+'失败：'+str(error)[:240]))
        threading.Thread(target=run,daemon=True).start()
    for label,action in [('一键启动 CTRL',start_ctrl),('重新检查',lambda:None),('网络检查',connectivity),('安装网站启动入口',install_entry)]:
        button=ttk.Button(actions,text=label,command=lambda l=label,a=action:work(l,a));button.pack(side='left',padx=(0,8));buttons.append(button)
    def copy_report():
        root.clipboard_clear();root.clipboard_append(report(state['rows']));root.update()
        status.set('已复制诊断摘要；不包含题目、截图、API Key 或浏览器登录数据。')
    ttk.Button(actions,text='复制诊断报告',command=copy_report).pack(side='left')
    footer=ttk.Frame(main);footer.pack(fill='x',pady=(10,0))
    ttk.Button(footer,text='启动并打开设置',command=lambda:work('打开设置',lambda:start_ctrl(True))).pack(side='left')
    ttk.Label(footer,text='服务只监听本机；关闭启动器不会关闭正在运行的助手。').pack(side='right')
    def drain():
        try:
            while True:
                ok,rows,message=events.get_nowait();state.update(rows=rows,busy=False)
                tree.delete(*tree.get_children())
                for row in rows: tree.insert('', 'end',values=(row['name'],row['state'],row['detail']))
                status.set(message)
                for button in buttons:button.configure(state='normal')
        except queue.Empty: pass
        root.after(100,drain)
    drain();work('环境检查',lambda:None)
    if smoke_report:
        def finish():
            if state['busy']:root.after(100,finish);return
            Path(smoke_report).write_text(json.dumps({'window':root.title(),'checks':len(tree.get_children()),'buttons':len(buttons)},ensure_ascii=False),encoding='utf-8');root.destroy()
        root.after(300,finish)
    root.mainloop()

def main():
    if getattr(sys, 'frozen', False):
        # Windowed executables have no standard streams; HTTP/Playwright expect them.
        if sys.stdout is None: sys.stdout = open(os.devnull, 'w')
        if sys.stderr is None: sys.stderr = open(os.devnull, 'w')
    if '--serve' in sys.argv:
        sys.argv.remove('--serve')
        import assistant_server
        assistant_server.main();return
    if '--launch' in sys.argv:
        sys.argv.remove('--launch')
        import start_assistant
        start_assistant.main();return
    parser=argparse.ArgumentParser()
    parser.add_argument('--diagnose',action='store_true')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--gui-smoke',type=Path,help=argparse.SUPPRESS)
    parser.add_argument('--runtime-check',type=Path,help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.runtime_check:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(); page.goto('about:blank')
            value = {'frozen':bool(getattr(sys,'frozen',False)), 'edge_launched':True,
                     'root':str(ROOT), 'version':browser.version}
            browser.close()
        args.runtime_check.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    elif args.diagnose:
        value=json.dumps(diagnose(),ensure_ascii=False,indent=2)
        if args.output:args.output.write_text(value,encoding='utf-8')
        elif sys.stdout:print(value)
    else: show_gui(args.gui_smoke)

if __name__=='__main__':main()
