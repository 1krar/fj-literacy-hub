# 素养聚合 · 信息素养比赛检索工作台

网站：[fj-literacy-hub.pages.dev](https://fj-literacy-hub.pages.dev/) · [题目路线助手使用说明](https://fj-literacy-hub.pages.dev/assistant-guide.html)

集中整理学术、标准、专利、统计、法律及备赛资源，帮助使用者自己快速检索。题目路线助手支持文本和截图、Gemini / DeepSeek 双模型并行、先完成先显示、逐步复制与跳转、独立 AI 作答及核验提示、手动重试和错误报告。模型回答需要人工核验。

## Windows 本机助手

1. 下载仓库 ZIP 并完整解压，或 `git clone` 此仓库。
2. 安装 Python 3.12 或更新版本及 Microsoft Edge。Python 安装时勾选加入 PATH。
3. 双击根目录的 `安装一键启动.cmd`。选择 Y 可在登录 Windows 后后台预启动，选择 N 可关闭；两种选择都会为当前 Windows 用户注册 `literacy-assistant://open`。缺少 Playwright 时安装器会联网安装。
4. 从网站大标题打开新助手标签；已预启动的服务会直接进入。服务未运行时在启动页点击原生“启动本机助手”链接，或双击 `启动比赛助手.cmd`。首次浏览器提示打开应用或访问本地网络时按需允许。
5. 在助手打开的 Gemini / DeepSeek 窗口登录你自己的账号。数据库网站使用普通 Edge 自己的登录状态。

本机地址：`http://127.0.0.1:8771/assistant.html`。网页服务只监听本机地址。请保持助手页打开，置顶小窗依赖该页面。普通 Edge 的模型登录不一定与助手独立模型窗口共享；新设备首次需要在模型窗口登录。

仓库附带 `vendor/evidence-chain` 的两个网页 Provider 分发快照，独立下载即可使用；无需另行下载整个证据链项目。如果相邻目录有 `evidence-chain`，优先复用该项目。也可设置 `EVIDENCE_CHAIN_ROOT` 指定连接组件目录、`LITERACY_ASSISTANT_PYTHON` 指定 Python 的完整路径。移动项目后重新安装启动入口。

## 静态使用与其他设备

打开网站的静态助手，复制提示词到自己的模型网页，再把完整 JSON 回答导入显示检索路线；手机、平板也可使用此方式。Windows 自动启动入口无法调用另一台电脑的本机服务。截图支持 PNG / JPEG，最多 5MB。

## Cloudflare Pages 部署

`dist/` 是可直接部署的静态文件。使用 Node.js 和 npm：

```sh
npm ci
npm run build
npx wrangler login
npx wrangler pages project create your-project-name
npx wrangler pages deploy dist --project-name=your-project-name
```

也可以在 Cloudflare Pages 直接上传 `dist/`。静态导航和手动助手无需 API 密钥。本仓库现有 `npm run deploy` 和 `cf:*` 是作者本机的加密凭证工作流，其他用户按以上 Wrangler 流程部署即可；仓库不包含作者的账号配置和凭证。

部署自己的域名时，自动检测接口目前只允许 `https://fj-literacy-hub.pages.dev`；需在 `scripts/assistant_server.py` 中将生产来源改成自己的精确 HTTPS 域名，再重启本机服务。模型控制接口保持本机同源并校验会话，勿开放公共访问。不能自动检测时仍可手动启动并进入本机地址。

## 开发检查

```sh
npm test
python -B -m unittest discover -s tests -p test_assistant_server.py
python -B -m unittest discover -s tests -p test_start_assistant.py
```

`npm run build` 使用已整理的资源和收藏夹 JSON，不需要原始 PDF。历史资料导入脚本需要自己的源文件，不属于正常安装步骤。

## 数据与账号

题目和截图仅在点击调用后发送到勾选的模型服务。浏览器配置、会话、截图上传临时文件在 `.runtime/`，不随源码分发。不要上传此目录、Cookie、`.env`、Cloudflare Token 或个人资料。公开资源链接的访问权限由原网站决定。

## 联系

QQ：2995267157 · 邮箱：kai666_2020@qq.com
