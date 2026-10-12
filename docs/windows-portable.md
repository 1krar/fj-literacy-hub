# Windows CTRL 助手运行包

适用于 Windows 10/11 x64。运行包自带 Python、GUI 和 Playwright 连接组件，无需安装 Node.js、Python 或完整证据链项目；使用 Microsoft Edge。API 使用联网服务，不代表无需网络。

1. 完整解压 ZIP 到桌面或文档目录。不要在压缩包内直接运行 EXE，也不要只复制 EXE。
2. 双击 `CTRLHelper.exe`，点击「一键启动 CTRL」。浏览器会打开 `http://127.0.0.1:8771/ctrl-assistant.html`。
3. 首次进入 CTRL 设置，填写这台电脑自己的千问或书生 API Key。其他电脑的加密配置不可直接搬用。
4. API 模式无需登录 Gemini/DeepSeek 网页。使用网页模式时，需要在助手自己的模型窗口登录，普通 Edge 的登录状态不一定共享。
5. 可选择「安装网站启动入口」，注册当前用户的 `literacy-assistant://open`，不要求管理员、不自动添加开机启动。

## 无法使用时

- 运行包文件缺失：完整重新解压，保留 `dist`、`vendor` 和 `_internal`。
- 保存目录不可写：移动整个目录到桌面或文档目录。
- 8771 端口被占用：优先复用已运行的正确助手；启动器不会强制关闭其他程序。
- API 未配置／加密配置无法读取：在当前电脑重新填写 API Key，不要发送到聊天里。
- 网络检查失败：检查互联网和系统代理。网络可达仅说明服务器能够连接，不验证 Key、模型权限或额度；模型实际调用错误仍在 CTRL 页面显示。
- 网页模型无法连接：确认 Edge 已安装，在 CTRL 设置连接对应模型并在独立窗口登录。

可点击「复制诊断报告」发给维护者，报告只含检查摘要，不读取原始日志、Cookie、API Key、题目或截图。`复制诊断报告`不能判断模型回答准确率。

后台只监听 `127.0.0.1`。关闭启动器不会关闭助手后台；题目保存在后台内存中，后台重启后通常清空。移动目录后重新安装网站启动入口。

## 从源码运行与构建

源码模式可执行 `python scripts/windows_launcher.py` 打开可视化启动器。构建者安装 PyInstaller 后执行 `python scripts/build_windows.py`；产物位于 `output/windows/CTRLHelper`，发布 ZIP 为上一级 `output/sites/ctrl-assistant-windows-x64.zip`。构建只收集公开文件，排除运行数据和凭证。

打包路径处理依据 [PyInstaller 运行时文档](https://pyinstaller.org/en/stable/runtime-information.html)。运行包使用单目录形式，请保留整个文件夹。
