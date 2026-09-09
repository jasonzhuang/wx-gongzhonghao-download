# 部署

当前服务通过微信读书 Web 读取公众号书架、文章列表和正文。它依赖非公开接口，适合个人或内部部署，不要直接暴露到公网：除可选的 `/mcp` 外，管理页、RSS 和导出接口没有统一鉴权。

## 前提

- Python 3.10+ 或 Docker；
- 一个可登录微信读书的微信账号；
- 已在微信读书 App 中关注至少一个目标公众号；
- 首次配置时，能在浏览器开发者工具中复制成功的 `/web/mp/articles` 请求为完整 cURL。

Cookie、`x-wr-ticket` 和 `x-wrpa-0` 都是敏感凭证，只能输入本机登录页，不要粘贴到聊天、Issue 或日志中。

## 检查并解压源码

在技能目录先检查捆绑包：

```bash
python3 scripts/self_test.py
```

然后解压到独立工作目录：

```bash
mkdir -p <工作目录>
tar -xzf assets/wechat-download-api-src.tar.gz -C <工作目录>
cd <工作目录>/wechat-download-api
cp env.example .env
```

至少核对 `.env` 中的：

```dotenv
SITE_URL=http://localhost:5000
PORT=5000
RSS_POLL_INTERVAL=7200
ARTICLES_PER_POLL=10
RSS_FETCH_FULL_CONTENT=true
RSS_CONTENT_CONCURRENCY=2
```

`SITE_URL` 必须是浏览器或 RSS 阅读器实际访问的服务根地址，否则图片代理和生成的 RSS 链接会错误。

## Docker

必须用当前捆绑源码本地构建，不要拉取可能仍使用旧文章链路的上游 `latest` 镜像：

```bash
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f wechat-api
```

仓库当前的 Compose 映射为 `5000:5000`。若 macOS 的 5000 端口被 AirPlay 占用，应把 Compose 改为：

```yaml
ports:
  - "5001:5000"
```

同时把 `.env` 的 `SITE_URL` 改成 `http://localhost:5001`。容器内端口仍是 5000，不要只改 `.env` 的 `PORT`；Dockerfile 的启动命令固定监听 5000。

`./data` 会挂载到容器内 `/app/data`，数据库和登录凭证都在其中持久化。

## 原生 Python

macOS/Linux：

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python app.py
```

Windows：

```bat
py -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python app.py
```

源码也提供 `start.sh` 和 `start.bat`。Linux 上以 root 运行 `start.sh` 会创建服务用户和 systemd 服务；不需要这些系统级改动时，使用上面的显式命令。

完全离线安装要求 Python 3.12。依次指定 `assets/wheels/any` 和当前平台目录：

- Windows x64：`win_amd64-cp312`
- Apple Silicon：`macosx_arm64-cp312`
- Mac Intel：`macosx_x86_64-cp312`

示例：

```bash
python3.12 -m venv venv
./venv/bin/pip install --no-index \
  --find-links <技能目录>/assets/wheels/any \
  --find-links <技能目录>/assets/wheels/macosx_arm64-cp312 \
  -r requirements.txt
```

依赖安装完成后仍用 `./venv/bin/python app.py` 启动服务。

## 配置登录

1. 打开 `<BASE>/login.html`。
2. 浏览器登录 `https://weread.qq.com`，打开任一公众号文章列表。
3. 在 Network 中找到成功的 `/web/mp/articles` 请求，选择“Copy as cURL”。
4. 把完整 cURL 只粘贴到本机登录页，点击“校验并保存”。

服务会提取 Cookie 和已有的 `x-wr-ticket` 或 `x-wrpa-0`，尝试续期，并在书架与文章列表两级在线校验通过后写入 `data/.weread_credentials.json`。扫码入口主要用于刷新普通 Cookie；首次配置或出现 `-2041` 时不能依赖扫码生成文章列表票据。

## 验收

从技能目录执行只读体检，`--base` 使用实际地址：

```bash
python3 scripts/verify_service.py --base http://127.0.0.1:5000
```

再打开 `<BASE>/rss.html`，添加一个书架公众号并只手动轮询一次。完整验收应同时满足：

- `/api/health` 返回 `status=healthy`；
- `/api/login/check` 返回 `success=true`；
- 至少发现一个 `MP_WXS_` 公众号；
- 轮询结果中 `failed=0`、`content_failed=0`；
- 订阅的 `article_count>0`、`export_count>0`；
- `/api/rss/all` 已包含文章条目。

`verify_service.py` 退出码：0 表示服务和在线认证正常，2 表示凭证或在线校验异常，3 表示服务不可达。它不会代替订阅和手动轮询验收。
