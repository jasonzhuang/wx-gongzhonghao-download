# OPERATIONS — 微信读书链路运营手册

下文 `<BASE>` 是本机服务地址。接口契约优先看 `<BASE>/api/docs`。

## 登录状态

- `/api/login/info` 只说明本地是否配置凭证；
- `/api/login/check` 才会在线验证 Cookie 和文章列表 WPA 凭证；
- 登录没有可信的固定 4 天寿命，不能用本地日期推断；
- `errCode=-2041` 优先检查 Ticket；非 JSON/跳登录页优先检查 Cookie；
- 更新方式是重新从浏览器 `/web/mp/articles` 请求复制两项凭证，再到
  `<BASE>/login.html` 校验保存。

## 订阅

搜索范围是微信读书书架。流程：

1. 在微信读书 App 关注公众号；
2. 服务管理页按名称搜索；
3. 选择 `MP_WXS_` 结果订阅；
4. 手动轮询一次确认。

旧数据库里的 Base64 FakeID 会在请求微信读书时自动转成 `MP_WXS_<数字>`。

## 轮询结果

`POST /api/rss/poll` 和 `/api/rss/status` 的最近结果包含：

- `ok` / `failed`：公众号列表请求成功/失败数；
- `fetched`：本轮取得的元数据数；
- `saved`：写库操作数；
- `content_failed`：正文失败数；
- `errors`：可诊断错误。

HTTP 200 不等于抓取成功。只有 `failed=0` 且 `content_failed=0` 才算完整成功。
失败时不会更新对应订阅的 `last_poll`。

## RSS 与导出

- 聚合 RSS：`<BASE>/api/rss/all`
- 单号 RSS：`<BASE>/api/rss/<MP_WXS_ID>`
- 导出：管理页支持 Markdown、HTML、Word、PDF、EPUB、Excel、JSON；可选快捷时间范围或自定义开始/结束日期
- 下载前会计算所选范围内的可导出文章数；超过 100 篇时应缩小日期范围分批导出，避免生成过大的 EPUB/Word 等文件

`article_count` 是已入库元数据数，`export_count` 是已有正文、可导出的数量。
两者不同意味着正文链路有失败，应查看最近轮询的 `content_failed/errors`。

## 频率和安全

- 默认 2 小时轮询、每号 10 篇、正文并发 2；
- 不要把间隔调到分钟级；
- 不要反复点击手动轮询验证无效凭证；
- 遇到 WPA、验证码或操作频繁时停止请求，稍后更新凭证；
- Cookie/Ticket/Wrpa 只在本机 `data/.weread_credentials.json`，备份时按敏感凭证处理。

## MCP

`.env` 设置 `ENABLE_MCP=1` 和随机长 `MCP_TOKEN` 后重启。MCP 搜索同样只查询
微信读书书架，订阅标识为 `MP_WXS_` BookId。
