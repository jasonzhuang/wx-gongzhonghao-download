# WeChat Download API — 微信读书链路版

本分支把公众号文章列表来源从已经失效的微信公众号后台
`/cgi-bin/appmsgpublish` 迁移到微信读书 Web：

```text
微信读书书架 /web/shelf/sync
  → 公众号 BookId（MP_WXS_<数字>）
  → 浏览器 /web/mp/articles cURL 提供初始 x-wr-ticket 或 x-wrpa-0
  → renewal 尝试续期已有文章列表票据
  → 文章列表 /web/mp/articles（Cookie + WPA）
  → 文章正文 /web/mp/content（reviewId）
  → SQLite / RSS / Markdown、HTML、Word、PDF、EPUB、Excel、JSON
```

改造依据：<https://github.com/tmwgsicp/wechat-download-api/issues/23>。

> 这是对微信读书非公开 Web 接口的兼容实现，不是腾讯官方 API。接口、Cookie
> 生命周期和风控策略都可能变化。当前实测资料显示文章列表还要求
> `x-wr-ticket` 或 `x-wrpa-0`。扫码协议只稳定提供普通 Web Cookie，首次
> 配置文章列表凭证需从浏览器 `/web/mp/articles` 请求导入完整 cURL；renewal
> 只用于尝试续期已有票据。

## 前提

1. 一个可以登录微信读书的普通微信账号，不再需要微信公众号管理员账号。
2. 先在微信读书 App 中关注至少一个目标公众号，使其出现在书架。
3. 一台运行 Python 3.10+ 或 Docker 的电脑。
4. 浏览器可以打开微信读书 Web，用开发者工具复制 `/web/mp/articles` 完整 cURL。

## 启动

### 原生 Python

```bash
cp env.example .env
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Windows 使用：

```bat
copy env.example .env
py -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

### Docker

上游公开镜像仍可能包含旧 `appmsgpublish` 实现。使用本分支时应从当前源码构建：

```bash
cp env.example .env
docker compose build
docker compose up -d
```

## 配置微信读书登录

1. 在微信读书 App 中关注目标公众号，使其出现在书架。
2. 浏览器登录 `weread.qq.com`，打开任一公众号文章列表。
3. 在开发者工具 Network 中找到 `/web/mp/articles`，复制该请求的完整 cURL。
4. 打开 `http://localhost:5000/login.html`，把 cURL 粘贴到本机表单中校验保存。
5. “扫码刷新 Cookie”仅用于刷新普通 Cookie；本机已有同账号票据时会尝试一并续期，不能替代首次 cURL 导入。

凭证会写入 `data/.weread_credentials.json`，权限尽量设为 `0600`。不得上传、
分享或提交该文件。也可以使用环境变量 `WEREAD_COOKIE`、`WEREAD_TICKET`、
`WEREAD_WRPA`、`WEREAD_VID`，但本地部署推荐登录页配置。

登录保存前会执行两级校验：

- `/web/shelf/sync` 校验 Cookie 并确认书架里有公众号；
- `/web/mp/articles` 校验导入或续期的文章列表票据确实可用。

## 订阅与轮询

管理页：`http://localhost:5000/rss.html`

- 搜索只在微信读书书架里的公众号中进行；
- 搜不到时先去微信读书 App 关注该公众号；
- 新订阅使用 `MP_WXS_<数字>` 作为本地标识；
- 旧数据库中的 Base64 FakeID 会在请求时自动转换，便于迁移；
- 默认每 2 小时轮询，正文并发默认为 2。

常用接口：

| 接口 | 说明 |
|---|---|
| `GET /api/health` | 服务健康 |
| `GET /api/login/info` | 本地是否已配置凭证 |
| `GET /api/login/check` | 在线校验 Cookie 和 WPA |
| `POST /api/login/qr/start` | 创建扫码登录会话并生成本地二维码 |
| `POST /api/login/qr/poll` | 轮询扫码确认状态，成功后自动保存凭证 |
| `GET /api/public/searchbiz?query=名称` | 搜索书架公众号 |
| `GET /api/public/articles?fakeid=MP_WXS_xxx` | 读取文章列表 |
| `POST /api/rss/subscribe` | 添加本地 RSS 订阅 |
| `POST /api/rss/poll` | 手动轮询并返回成功/失败统计 |
| `GET /api/rss/status` | 轮询器与最近一次结果 |
| `GET /api/rss/all` | 聚合 RSS |

手动轮询不再把失败伪装成成功。响应包含：

```json
{
  "ok": 1,
  "failed": 0,
  "fetched": 10,
  "saved": 10,
  "content_failed": 0,
  "errors": []
}
```

只有文章列表请求成功时才更新 `last_poll`。Cookie/WPA 失效、`-2041`、
非 JSON 登录页和正文容器缺失都会成为显式错误。

## 数据和导出

所有本地数据在 `data/`：

- `data/rss.db`：订阅与文章；
- `data/.weread_credentials.json`：敏感登录凭证。

导出只包含已经抓到正文的记录（`content != ''`）。文章列表成功但正文失败时，
轮询结果会在 `content_failed` 和 `errors` 中明确报告，不再静默显示为可下载 0 篇。

## 配置项

| 变量 | 默认值 | 说明 |
|---|---:|---|
| `WEREAD_COOKIE` | 空 | 微信读书 Cookie，建议通过登录页保存 |
| `WEREAD_TICKET` | 空 | 可选备用的 `x-wr-ticket` |
| `WEREAD_WRPA` | 空 | 可选备用的 `x-wrpa-0` |
| `WEREAD_VID` | 自动提取 | 微信读书用户 VID |
| `RSS_POLL_INTERVAL` | `7200` | 轮询间隔（秒） |
| `ARTICLES_PER_POLL` | `10` | 每号每轮最多处理篇数 |
| `RSS_FETCH_FULL_CONTENT` | `true` | 是否抓正文 |
| `RSS_CONTENT_CONCURRENCY` | `2` | 正文并发数 |
| `SITE_URL` | `http://localhost:5000` | 图片代理和 RSS 基础地址 |

## 已知限制

- renewal 是非公开 Web 行为，无法保证从普通扫码 Cookie 生成文章列表票据；首次配置或 `-2041` 时需重新导入 `/web/mp/articles` 完整 cURL；
- 微信读书 Web 接口不是稳定公开协议，部署成功不代表长期无需维护；
- 公众号发现范围是微信读书书架，不再依赖公众号后台的全局 `searchbiz`；
- 当前没有绕过 WPA、验证码或频控的逻辑，遇到验证应停止轮询并更新凭证；
- Cookie/WPA 的精确寿命未知，因此状态检查必须在线请求，不能靠本地固定过期时间。

## 许可证

本项目继续遵守上游 AGPL-3.0，详见 [LICENSE](LICENSE)。个人或内部使用公开文章，
请遵守微信读书、微信公众平台及当地法律的相关条款。
