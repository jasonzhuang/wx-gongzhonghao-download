# 运营与使用

下文 `<BASE>` 表示实际服务根地址，例如 `http://127.0.0.1:5000`。完整接口参数以 `<BASE>/api/docs` 为准。

## 页面入口

| 地址 | 用途 |
|---|---|
| `/admin.html` | 服务状态、文章查询和管理入口 |
| `/login.html` | 导入或刷新微信读书凭证 |
| `/rss.html` | 搜索、订阅、轮询、文章下载和整号导出 |
| `/history.html` | 按游标继续补抓更早文章 |
| `/categories.html` | 管理分类和分类 RSS |
| `/blacklist.html` | 暂停指定公众号的自动轮询 |
| `/api/docs` | OpenAPI 接口文档 |

## 日常流程

1. 在微信读书 App 中关注目标公众号。
2. 打开 `/login.html` 导入同一会话中成功的 `/web/mp/articles` 完整 cURL。
3. 打开 `/rss.html` 按名称搜索并订阅；搜索范围只包含当前微信读书书架。
4. 首次订阅后手动轮询一次，确认列表和正文均成功。
5. 后续由后台轮询器按 `RSS_POLL_INTERVAL` 自动更新。

批量订阅每次最多处理 20 个名称。多条同名结果需要人工确认，服务不会盲目订阅。

## 登录状态

- `GET /api/login/info` 只表示本地是否存在凭证；
- `GET /api/login/check` 会在线验证 Cookie、书架和文章列表票据；
- `GET /api/admin/status` 也会执行在线校验，供管理页刷新状态；
- 登录没有可信的固定寿命，应以在线校验结果为准；
- 首次配置或 `errCode=-2041` 时，重新导入浏览器中成功的 `/web/mp/articles` 完整 cURL；
- 扫码仅在本机已有同一账号票据时适合刷新 Cookie 并尝试续期票据。

凭证默认保存在 `data/.weread_credentials.json`；`.env` 中的 `WEREAD_*` 仅作为无状态部署回退。

## 轮询结果

手动触发：

```bash
curl -X POST http://127.0.0.1:5000/api/rss/poll
```

状态查询：`GET <BASE>/api/rss/status`。最近结果中的字段含义：

| 字段 | 含义 |
|---|---|
| `ok` / `failed` | 文章列表成功/失败的公众号数 |
| `fetched` | 本轮从列表取得的文章元数据数 |
| `saved` | 本轮新增入库的文章数；补全已有记录的正文不计入 |
| `content_failed` | 正文获取或解析失败的文章数 |
| `errors` | 公众号、正文或黑名单跳过信息 |

HTTP 200 不代表业务成功。完整成功要求响应的 `success=true`，并且 `failed=0`、`content_failed=0`。列表失败时不会更新该订阅的 `last_poll`。黑名单中的订阅保留数据和订阅关系，但自动轮询会跳过。

## 历史文章与导出

`/history.html` 每次可设置 1–100 篇的目标数量；服务按完整分页保存，实际取得数可能略多。下一次从上次游标继续，并为尚无正文的文章补抓正文。

`/rss.html` 支持两类整号导出：

- “全部”只导出本地已经入库且已有正文的文章，不会无界扫描微信读书历史；
- 自定义日期范围会先扫描到起始时间、补齐范围内正文，再生成文件。

超过 100 篇时终止下载和提示分批的软限制目前已停用，系统会继续补抓并下载；相关分支仍保留在代码注释中，便于以后恢复。后端各格式的技术上限仍为：

| 格式 | 单次上限 | 内容 |
|---|---:|---|
| Markdown ZIP、HTML、Excel、JSON | 3000 | Markdown/HTML 为正文合集；Excel/JSON 为元数据 |
| Word、EPUB | 500 | 内嵌图片的离线正文合集 |
| PDF | 200 | 内嵌图片的离线正文合集 |

导出只统计 `content` 非空的记录。`article_count` 是已入库的文章元数据数，`export_count` 是已有正文、可导出的文章数；两者不一致时先查看 `content_failed` 和 `errors`。

单篇下载和程序化增量同步：

- `GET /api/feed/articles.json?since=0&limit=50`：默认按发布时间正序返回元数据和 `next_since`，单次最多 200 条；传 `order=desc` 时优先返回最新文章，供展示或按篇下载；
- `GET /api/feed/article/{id}.md`：带 YAML frontmatter 的 Markdown；
- `GET /api/feed/article/{id}.html`：单篇 HTML；
- 正文尚未抓取时，单篇下载返回 422。

## RSS

- 聚合：`<BASE>/api/rss/all`；
- 单个公众号：`<BASE>/api/rss/<MP_WXS_ID>`，默认 30、最多 50 篇；
- 历史：`<BASE>/api/rss/<MP_WXS_ID>/history`，默认每页 500、最多 5000 篇；
- 分类：`<BASE>/api/rss/category/<CATEGORY_ID>`；
- 订阅列表可从 `/api/rss/export?format=csv` 或 `format=opml` 导出。

常规单号 RSS 只包含订阅后的轮询文章；通过历史补抓得到的文章使用历史 RSS。

## 频率、备份与安全

- 默认每 2 小时轮询、每号每轮最多 10 篇、正文并发 2；
- 不要改成分钟级轮询，也不要连续点击手动轮询测试失效凭证；
- 遇到 WPA、验证码或“操作频繁”应停止请求，先在浏览器完成验证或更新凭证；
- 备份 `data/rss.db`；若要保留登录态，再单独安全备份 `data/.weread_credentials.json`；
- 恢复或升级前先停止服务，替换源码后保留 `data/` 和 `.env`；Docker 部署需要重新 `docker compose build`；
- 不要将整个服务直接暴露到公网。

## 可选 MCP

在 `.env` 设置 `ENABLE_MCP=1` 和随机长 `MCP_TOKEN`，重启后连接 `<BASE>/mcp`，请求头使用 `Authorization: Bearer <MCP_TOKEN>`。`MCP_RESOURCE_URL` 应填写客户端实际访问的 MCP URL，用于 DNS-rebinding 的 Host/Origin 白名单。

Bearer Token 只保护 `/mcp`，不会给其他页面和 API 增加鉴权。MCP 的搜索范围同样仅限微信读书书架。
