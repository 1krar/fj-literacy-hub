# Windows 7 API 兼容试用版

保留 CTRL 的截图/文字、关键词与网站建议、多任务六并发、问答案、复核与重试。仅调用千问和书生 API；不支持 Gemini/DeepSeek 网页自动化和原生 Tk 启动器。

## 使用

1. 适用于 Windows 7 **SP1**。64 位系统使用 x64 包，32 位系统使用 x86 包；完整解压到可写目录。不能只复制启动脚本或运行时 EXE。
2. 双击根目录 `启动 CTRL 助手.cmd`。它使用包内 `runtime/python.exe`，无需安装 Python、Node 或 Playwright。运行后后台只监听本机 `127.0.0.1:8771`。
3. 使用 Edge 109 或支持 ES modules/现代 JavaScript 的相容 Chromium 浏览器；Internet Explorer 不支持。首次在 CTRL 设置中填写自己的 Key。
4. 无法使用时双击 `启动诊断.cmd`，打开浏览器诊断页。检查文件、保存目录、端口、API 配置与网络，可复制不含题目或 Key 的诊断摘要。
5. 点击「置顶小窗」另开紧凑窗口，使用 Windows 原生置顶，而非新版浏览器 Document PiP。允许本机弹窗后，小窗会置顶；可点「取消置顶」或关闭小窗。主页面保留，小窗关闭不结束后台任务。任务列表和结果共用后台；页面局部选项与滚动位置各自保留。
6. 主页面或小窗中可直接 Ctrl+V 粘贴截图，也可拖图。浏览器能读出的图片直接处理；浏览器未提供图片/文字时，使用 Windows 剪贴板补读。也可点「粘贴截图」显式读取。只在这些操作时读取图片，不定时读取剪贴板、不读取剪贴板文本、不修改剪贴板。自动识题开关仍有效；取消勾选后仅预览待提交。

如果运行时本身无法启动，先确认 SP1、系统位数、完整解压和 Windows 运行库更新。不要从不明网站下载 DLL。SSL/TLS 或证书错误需要修复系统证书、日期或网络；程序不会关闭 HTTPS 证书校验。已运行的同端口正确助手会被复用，不强制结束其他程序。

配置使用 Windows 当前用户 DPAPI 加密；运行包不包含维护者的 Key、截图、Cookie 或运行记录。首次新设备需重新填写 Key。关闭浏览器不关闭后台；后台重启后题目历史不保留。

## 支持范围与验证

这是针对 Win7 的兼容试用包，不是已在 Win7 实机全面验收的发行版。构建与 Python 3.8 测试在 Windows 11 上执行；还需在目标 Win7 电脑检查启动、TLS/API 网络、截图粘贴和浏览器布局。

运行时采用 [Python 官方 3.8.10 嵌入式分发](https://www.python.org/downloads/release/python-3810/)，仅使用标准库与本项目源码，保留官方许可证。Python 3.8 已停止维护；建议只作兼容过渡，不将本机服务暴露公网。

原生功能依据微软的 [SetWindowPos](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowpos)、[剪贴板格式转换](https://learn.microsoft.com/en-us/windows/win32/dataxchg/clipboard-formats) 和 [GetDIBits](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-getdibits)。只接受本程序生成的随机小窗标题，并核对其进程为 Edge，不设置其他窗口置顶。截图最大 5 MB；剪贴板无图片时提示使用截图工具或拖入图片。

## 构建

开发电脑执行 `python scripts/build_windows7.py`，下载经过公开校验值核对的官方 32/64 位嵌入式 Python，打包公开前端及 API 源码。ZIP 输出到上一级 `output/sites/ctrl-assistant-win7-api-x64.zip` 与 `ctrl-assistant-win7-api-x86.zip`。不会安装系统 Python或改动系统代理、证书与安全策略。
