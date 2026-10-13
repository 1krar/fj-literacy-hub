# Cloudflare 网站访问验证

线上 Pages 使用 `dist/_worker.js` 与全路径 `_routes.json` 进行服务端密码验证。未验证时 HTML 显示密码页，JS、JSON 等资源返回 401；验证后使用 Secure、HttpOnly、SameSite=Lax 的 HMAC 签名 Cookie，有效期 8 小时。登录后回到最初请求的页面。

密码摘要与随机会话密钥作为 Cloudflare production/preview 的 `secret_text` 环境绑定保存，不放入公开源码、前端、运行包或日志。配置缺失或验证服务异常时返回 503；deployment config 的 `fail_open` 设置为 false。

更新密码时通过标准输入传给 `scripts/cloudflare.mjs access-setup`，然后按项目流程验证并重新部署。它更新两个环境并更换签名密钥，已有验证会话随之失效。不要把实际密码写进公开文档或命令脚本。

此验证针对使用新 Worker 的线上部署；本机助手和公开 GitHub 源码不受它控制，历史部署也不会被追溯改写。

实现依据 [Pages Advanced mode](https://developers.cloudflare.com/pages/functions/advanced-mode/) 与 [Pages 项目配置 API](https://developers.cloudflare.com/api/resources/pages/subresources/projects/methods/edit/)。静态下载包现在包含 Worker；在 Cloudflare 部署时须配置访问秘密，本机静态服务器不执行 Worker。
