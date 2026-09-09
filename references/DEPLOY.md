# DEPLOY — 微信读书链路安装手册

## 1. 部署前检查

检查操作系统/架构、Python 3.10+、Docker、5000/5001 端口和网络。
macOS AirPlay 常占 5000，直接改 5001。先运行：

```bash
python3 scripts/self_test.py
```

用户必须已经：

- 能登录 `https://weread.qq.com`；
- 在微信读书 App 关注至少一个公众号；
- 接受从浏览器开发者工具复制完整 Cookie 到本机服务。

## 2. 解压源码

建议工作目录：macOS/Linux `~/wechat-mp-rss/`，Windows
`%USERPROFILE%\wechat-mp-rss\`。

```bash
tar -xzf assets/wechat-download-api-src.tar.gz -C <工作目录>
cd <工作目录>/wechat-download-api
cp env.example .env
```

按实际端口修改 `.env` 的 `PORT` 与 `SITE_URL`。默认已经设置：

```dotenv
RSS_POLL_INTERVAL=7200
RSS_CONTENT_CONCURRENCY=2
RSS_FETCH_FULL_CONTENT=true
```

## 3A. Docker

不要使用上游 `latest` 镜像，它可能仍是旧 `appmsgpublish` 链路。捆绑源码的
`docker-compose.yml` 已经固定为本地构建：

```yaml
services:
  wechat-api:
    build: .
    container_name: wechat-mp-rss
    restart: unless-stopped
    ports:
      - "5001:5000"
    volumes:
      - ./data:/app/data
      - ./.env:/app/.env:ro
    environment:
      - TZ=Asia/Shanghai
```

启动：

```bash
docker compose build
docker compose up -d
docker compose ps
```

凭证写入 `data/.weread_credentials.json`，不写只读 `.env`。

## 3B. 原生 Python

联网安装：

```bash
bash start.sh
```

Windows 在源码目录执行 `start.bat`。PyPI 较慢时可配置清华或阿里镜像。

完全离线安装要求 Python 3.12。根据平台组合 `assets/wheels/any` 与对应目录：

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
./venv/bin/python app.py
```

## 4. 配置认证

1. 浏览器打开 `weread.qq.com` 并扫码登录。
2. 打开开发者工具 Network。
3. 打开任一微信读书公众号文章列表。
4. 找到 `/web/mp/articles` 请求。
5. 在该请求上选择 “Copy as cURL”，复制完整 cURL，而不是只复制 Cookie。
6. 打开 `<BASE>/login.html`，只在本机页面粘贴并校验；服务会提取 Cookie
   以及请求中已有的 `x-wr-ticket` 或 `x-wrpa-0`，并尝试通过 renewal 续期。

扫码入口只负责刷新普通 Web Cookie；只有本机已有同账号文章列表票据时才会
尝试复用。首次配置不能依赖扫码自动生成票据。

不要让用户把凭证发进聊天。登录页只有在线校验成功才会写盘。

## 5. 验证

```bash
python3 scripts/verify_service.py --base http://127.0.0.1:5001
```

然后在 RSS 页面添加一个书架公众号，只触发一次轮询：

```bash
curl -X POST http://127.0.0.1:5001/api/rss/poll
```

成功响应必须同时满足 `failed=0`、`content_failed=0`，且订阅列表中
`article_count` 和 `export_count` 都大于 0。
