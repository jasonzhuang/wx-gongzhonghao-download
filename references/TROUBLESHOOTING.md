# 排错

先从技能目录运行只读体检：

```bash
python3 scripts/verify_service.py --base http://127.0.0.1:5000
```

再依次检查：

1. `GET <BASE>/api/health`：服务和端口；
2. `GET <BASE>/api/login/check`：Cookie、书架和文章列表票据；
3. `GET <BASE>/api/rss/status`：轮询器和最近一次结果；
4. `GET <BASE>/api/rss/subscriptions`：`article_count` 与 `export_count`。

不要通过连续手动轮询来测试失效凭证。

## 常见问题

| 症状 | 原因 | 处理 |
|---|---|---|
| 服务不可达 | 进程、容器或端口不正确 | 检查进程、Compose 状态和日志；确认访问的是实际映射端口 |
| Docker 改成 5001 后仍打不开 | 只改了 `.env`，未改宿主机端口映射 | Compose 使用 `5001:5000`，并设置 `SITE_URL=http://localhost:5001`；容器内仍监听 5000 |
| `/api/login/info` 成功但 `/api/login/check` 失败 | 本地有凭证，但远端登录态或 WPA 已失效 | 以 `/api/login/check` 为准，重新导入成功的 `/web/mp/articles` 完整 cURL |
| `errCode=-2041` | `x-wr-ticket`/`x-wrpa-0` 缺失、过期、不匹配，或触发风险验证 | 在浏览器完成可能出现的验证；复制同一会话中成功的 `/web/mp/articles` 完整 cURL 到本机登录页 |
| 首次扫码后仍提示没有文章列表票据 | 扫码只稳定取得普通 Web Cookie | 不要反复扫码，改用 `/web/mp/articles` 完整 cURL 完成首次配置 |
| `shelf/sync` 返回非 JSON 或登录页 | Cookie 失效 | 重新登录 `weread.qq.com`，再导入新的完整 cURL |
| 登录校验提示书架没有公众号 | 微信读书书架为空 | 先在微信读书 App 关注至少一个公众号 |
| 搜不到公众号 | 搜索只查询当前书架 | 先在 App 关注，确认名称后重试 |
| 手动轮询 HTTP 200，但 `success=false` 或 `failed>0` | 业务请求失败 | 查看响应中的 `errors`；不要只看 HTTP 状态码 |
| `content_failed>0` | `/web/mp/content` 获取失败或正文容器解析失败 | 停止重复轮询，检查错误与登录状态；更新凭证后重新轮询，必要时用历史或日期范围补抓 |
| `article_count>0`、`export_count=0` | 只有元数据，没有成功保存正文 | 查看最近轮询的 `content_failed/errors`，确认 `RSS_FETCH_FULL_CONTENT=true` |
| 某公众号 `last_poll` 不更新 | 该公众号的列表请求失败 | 按该公众号在 `errors` 中的错误处理；失败时不更新时间是预期行为 |
| 历史获取立即显示已到最早 | 历史游标已完成 | 若需要指定日期范围，从 `/rss.html` 使用自定义时间范围，服务会重新扫描边界 |
| 自定义范围提示超过 100 篇 | 超过前端建议批量大小 | 缩小开始/结束日期并分批导出 |
| 导出 404 或篇数少于 `article_count` | 所选范围没有已抓到正文的文章 | 先补抓正文；导出只包含 `content` 非空的记录 |
| 单篇 Feed 返回 422 | 该文章正文尚未抓取 | 等待下一轮或修复认证后重新补抓 |
| RSS 图片或链接指向错误端口/域名 | `SITE_URL` 与实际访问地址不一致 | 修改 `.env` 的 `SITE_URL` 后重启服务 |
| `/mcp` 404 | MCP 未启用或缺少 Token | 设置 `ENABLE_MCP=1` 和非空 `MCP_TOKEN` 后重启 |
| `/mcp` 401 | Bearer Token 缺失或不一致 | 发送 `Authorization: Bearer <MCP_TOKEN>`；检查客户端配置 |
| Docker 仍请求 `appmsgpublish` | 使用了旧镜像 | 用当前捆绑源码执行 `docker compose build`，不要拉上游 `latest` |

`verify_service.py` 返回 0 只说明服务与在线认证正常；没有订阅、尚未轮询或没有可导出正文时，仍需在 `/rss.html` 完成首次订阅和轮询。

## 日志

Docker：

```bash
docker compose logs -f wechat-api
```

原生前台运行时直接查看启动终端；systemd 部署使用：

```bash
journalctl -u wechat-article-api -f
```

优先搜索：`-2041`、`认证失败`、`非 JSON`、`正文响应中没有文章内容容器`、`content_failed`。

## 提交诊断信息

可以提供：

- `verify_service.py` 输出；
- `/api/rss/status` 的 `last_result`；
- 出错公众号的 `MP_WXS_` 标识；
- 错误码、错误消息和服务启动方式；
- 捆绑源码包哈希。

不要提供 Cookie、`x-wr-ticket`、`x-wrpa-0`、完整 cURL、`.env` 或 `.weread_credentials.json`。
