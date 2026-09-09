---
name: wechat-mp-rss
description: 在本机部署和运营基于微信读书 Web 的微信公众号订阅、正文抓取、RSS 与批量导出服务。适用于公众号文章归档、RSS、Markdown/Word/PDF 导出，以及 Cookie/WPA 失效、文章为 0、轮询失败等排障。
---

# 微信公众号批量抓取服务（微信读书链路）

## 方案状态

原项目依赖的微信公众号后台 `appmsgpublish` 文章列表接口已于 2026-07
失效。本技能内的捆绑源码已经参考上游 Issue #23 改为微信读书 Web 链路：

```text
微信读书书架 → MP_WXS BookId → 文章列表 → reviewId 正文 → SQLite/RSS/导出
```

具体接口：

- `/web/shelf/sync`：读取书架公众号；
- `/web/login/renewal`：续期 Cookie，并尝试刷新已有的 `x-wr-ticket` 或 `x-wrpa-0`；
- `/web/mp/articles`：读取文章列表，需要 Cookie + 一种 WPA 凭证；
- `/web/mp/content`：按 `reviewId` 获取完整文章 HTML。

这是非公开 Web 接口兼容方案，不承诺长期稳定。扫码只稳定取得普通 Web Cookie；
首次配置或票据失效时，用户需从浏览器成功的 `/web/mp/articles` 请求导入完整
cURL。renewal 只尝试续期已有文章列表票据；不得声称“永久免登录”或“官方支持”。

## 硬前提

1. 一个可登录微信读书的普通微信账号，不需要微信公众号管理员账号。
2. 用户先在微信读书 App 中关注至少一个目标公众号，使其出现在书架。
3. 用户本人在浏览器打开 `weread.qq.com` 扫码登录，并从开发者工具中复制
   同一登录会话里成功的 `/web/mp/articles` 完整 cURL；本机服务从中提取
   Cookie 和 Ticket/Wrpa。
4. 一台可持续运行服务的 Windows/macOS 电脑。

Cookie、Ticket、Wrpa 都是敏感凭证。AI 只能引导用户填入本机登录页，不能要求用户在聊天中
粘贴、上传或分享。凭证只存 `data/.weread_credentials.json`。

## 安装

先运行：

```bash
python3 scripts/self_test.py
```

源码在 `assets/wechat-download-api-src.tar.gz`，解压后选择：

- Docker：必须从捆绑源码本地 `docker compose build`；不要拉取仍可能包含旧链路的
  `tmwgsicp/wechat-download-api:latest`。
- 原生 Python：Python 3.10+，用 `start.sh` / `start.bat`；完全离线安装要求
  Python 3.12 和 `assets/wheels/`。

端口默认 5000；macOS AirPlay 冲突时用 5001，并同步修改 `SITE_URL`。
完整命令见 `references/DEPLOY.md`。

## 部署后流程

1. 打开 `http://localhost:<端口>/login.html`。
2. 用户本人粘贴成功的 `/web/mp/articles` 完整 cURL；页面提取凭证、尝试续期、
   在线校验后再保存。扫码入口仅用于刷新同账号 Cookie 和续期已有票据。
3. 运行 `scripts/verify_service.py --base http://127.0.0.1:<端口>`。
4. 到 RSS 页面搜索微信读书书架中的公众号并订阅。
5. 只手动触发一次 `POST /api/rss/poll`，检查返回的 `failed`、
   `content_failed` 和 `errors`，不能只看 HTTP 200。

## 成功标准

- `/api/health` 返回健康；
- `/api/login/check` 在线校验成功；
- 书架至少发现 1 个 `MP_WXS_` 公众号；
- 手动轮询 `failed=0` 且 `content_failed=0`；
- 至少一个订阅的 `article_count > 0` 且 `export_count > 0`；
- `/api/rss/all` 含文章条目；
- `verify_service.py` 退出码 0。

## 运营边界

- 默认 `RSS_POLL_INTERVAL=7200`，正文并发 `RSS_CONTENT_CONCURRENCY=2`；
- 不要分钟级轮询，不要反复用手动轮询测试失效 WPA；
- `errCode=-2041` 通常表示 `x-wr-ticket`/`x-wrpa-0` 缺失、失效、不匹配，
  或微信读书要求完成风险验证；
- 登录寿命没有可靠固定天数，只能以 `/api/login/check` 在线结果为准；
- 搜索范围是微信读书书架，搜不到时先去微信读书 App 关注；
- 不绕过 WPA、验证码或频率限制；遇到验证应停止请求并更新凭证；
- 仅限个人或内部使用公开文章，遵守上游 AGPL-3.0 和平台条款。

部署、日常操作和排错分别见：

- `references/DEPLOY.md`
- `references/OPERATIONS.md`
- `references/TROUBLESHOOTING.md`
