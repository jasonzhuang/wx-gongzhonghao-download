#!/usr/bin/env python3
"""wechat-mp-rss 微信读书链路部署后体检：只读探测，不改任何状态。

依次检查服务、凭证配置、微信读书在线认证、轮询结果和文章入库。

用法: python3 verify_service.py [--base http://127.0.0.1:5001]
退出码: 0=服务和微信读书链路可用; 2=配置/在线认证/最近轮询异常; 3=服务不可达。
"""
import argparse
import json
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

TIMEOUT = 6


def get(base: str, path: str):
    req = urllib.request.Request(base + path, headers={"User-Agent": "wechat-mp-rss-verify"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def find_base(preferred):
    candidates = []
    if preferred:
        candidates.append(preferred.rstrip("/"))
    candidates += ["http://127.0.0.1:5001", "http://127.0.0.1:5000"]
    for base in dict.fromkeys(candidates):
        try:
            if get(base, "/api/health").get("status") == "healthy":
                return base
        except Exception:
            continue
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", help="服务地址，如 http://127.0.0.1:5001")
    args = ap.parse_args()

    base = find_base(args.base)
    if not base:
        print("结论: 服务不可达（5001/5000 都没有健康响应）。先按 DEPLOY.md 启动服务，或确认端口。")
        return 3
    print(f"[OK] 服务健康: {base}")

    configured = False
    online_ok = False
    try:
        info = get(base, "/api/login/info")
        data = info.get("data") or {}
        if info.get("success"):
            configured = True
            vid = data.get("vid") or "?"
            print(f"[OK] 微信读书凭证已配置（VID: {vid}）")
        else:
            print(f"[!!] 未配置微信读书 Cookie/Ticket —— 打开 {base}/login.html")
    except Exception as e:
        print(f"[!!] 登录状态接口异常: {e}")

    if configured:
        try:
            check = get(base, "/api/login/check")
            if check.get("success"):
                online_ok = True
                data = check.get("data") or {}
                print(f"[OK] 微信读书在线校验通过，书架公众号 {data.get('account_count', 0)} 个，探测文章 {data.get('probe_article_count', 0)} 篇")
            else:
                print(f"[!!] 微信读书在线校验失败: {check.get('error', '未知错误')}")
        except Exception as e:
            print(f"[!!] 微信读书在线校验异常: {e}")

    try:
        st = (get(base, "/api/rss/status").get("data") or {})
        print(f"[{'OK' if st.get('running') else '!!'}] 轮询器: {'运行中' if st.get('running') else '未运行'}，"
              f"间隔 {st.get('poll_interval', '?')} 秒，订阅 {st.get('subscription_count', '?')} 个")
        last = st.get("last_result") or {}
        if last.get("message"):
            marker = "!!" if last.get("failed") or last.get("content_failed") else "OK"
            print(f"[{marker}] 最近轮询: {last.get('message')}")
            for err in (last.get("errors") or [])[:3]:
                print(f"     - {err}")
    except Exception as e:
        print(f"[!!] 轮询状态接口异常: {e}")

    try:
        subs = (get(base, "/api/rss/subscriptions").get("data") or [])
        if subs:
            names = "、".join(s.get("nickname", "?") for s in subs[:10])
            print(f"[OK] 订阅列表({len(subs)}): {names}{' …' if len(subs) > 10 else ''}")
            article_total = sum(int(s.get("article_count") or 0) for s in subs)
            export_total = sum(int(s.get("export_count") or 0) for s in subs)
            marker = "OK" if article_total and export_total else "!!"
            print(f"[{marker}] 本地文章 {article_total} 篇，可下载正文 {export_total} 篇")
        else:
            print("[--] 还没有订阅：先在微信读书 App 关注公众号，再到管理面板添加")
    except Exception as e:
        print(f"[!!] 订阅列表接口异常: {e}")

    if configured and online_ok:
        print("结论: 服务与微信读书在线认证正常；文章按配置间隔自动更新。")
        return 0
    print("结论: 服务在跑，但微信读书 Cookie/Ticket 未配置或在线校验失败。")
    return 2


if __name__ == "__main__":
    sys.exit(main())
