# TROUBLESHOOTING — 微信读书链路排错

先运行 `scripts/verify_service.py`，再根据以下信号处理。不要反复手动轮询。

| 症状 | 判断 | 处理 |
|---|---|---|
| 服务不可达 | 服务或端口问题 | 查进程/容器日志，确认 5000/5001 与 `SITE_URL` |
| `errCode=-2041` | 文章列表票据缺失、过期、不匹配，或触发微信读书风险验证 | 浏览器打开公众号文章列表并完成可能出现的验证；从成功的 `/web/mp/articles` 请求复制完整 cURL，在本机登录页重新导入 |
| 扫码后文章探测仍返回 `-2041` | 扫码只取得普通 Cookie，未取得文章列表票据 | 不要反复扫码；从浏览器 `/web/mp/articles` 请求复制完整 cURL。服务不会再把 HTTP 200 中的 `-2041` 当成登录成功 |
| `shelf/sync` 返回登录页或非 JSON | Cookie 失效 | 重新登录 `weread.qq.com` 后更新凭证 |
| 登录校验说书架无公众号 | 微信读书尚未关注公众号 | 在微信读书 App 关注至少一个公众号后重试 |
| 管理页搜不到公众号 | 搜索仅查微信读书书架 | 先在 App 关注；确认名称或直接查 `MP_WXS_` BookId |
| 轮询 `failed>0` | 文章列表请求失败 | 查看 `errors`；不要把 HTTP 200 当成功 |
| `article_count=0` | 列表未入库 | 先查 `/api/login/check`，再只触发一次轮询 |
| `article_count>0`、`export_count=0` | 正文全部失败 | 查看 `content_failed/errors`；检查 `/web/mp/content` 响应是否有正文容器 |
| 最近轮询时间不更新 | 对应公众号请求失败 | 这是新实现的正确行为，按错误信息排查 |
| 图片裂开 | `SITE_URL` 不匹配 | 修改 `.env` 后重启 |
| Docker 使用后仍走 `appmsgpublish` | 拉了上游旧镜像 | 用捆绑源码执行 `docker compose build`，不要拉 `latest` |

## 日志

- Docker：`docker compose logs -f wechat-api`
- 原生：启动终端或项目日志目录

重点检索：`-2041`、`认证失败`、`非 JSON`、`正文响应中没有文章内容容器`、
`content_failed`。

## 仍无法定位

收集以下不含敏感凭证的信息：

- `verify_service.py` 输出；
- `/api/rss/status` 的 `last_result`；
- 出错公众号的 `MP_WXS_` 标识；
- 错误码和错误消息；
- 服务版本/源码包哈希。

不要收集或发送 Cookie、`x-wr-ticket`、`x-wrpa-0`、`.weread_credentials.json`。
