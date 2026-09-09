#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2026 tmwgsicp
# Licensed under the GNU Affero General Public License v3.0
# See LICENSE file in the project root for full license text.
# SPDX-License-Identifier: AGPL-3.0-only
"""
Feed 路由 - 本地已抓取文章的元数据列表 + 单篇 markdown 导出

单租户、私有部署，无需鉴权：
- GET /api/feed/articles.json  按时间游标增量拉取本地文章（含 id）
- GET /api/feed/article/{id}.md 按 id 取单篇 markdown 正文（带 YAML frontmatter）
"""

import os
import logging
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response

from utils import rss_store
from utils.image_proxy import proxy_image_url

logger = logging.getLogger(__name__)

router = APIRouter()


def _base_url(request: Request) -> str:
    """优先用 SITE_URL，否则回退请求 base_url（用于图片代理）。"""
    site = os.getenv("SITE_URL", "").strip().rstrip("/")
    return site or str(request.base_url).rstrip("/")


@router.get("/feed/articles.json", summary="本地已抓取文章列表（含 id，增量同步）")
async def feed_articles(
    request: Request,
    since: int = Query(0, ge=0, description="Unix 时间戳，返回 publish_time > since 的文章；首次传 0"),
    fakeid: Optional[str] = Query(None, description="可选，筛选单个公众号"),
    limit: int = Query(50, ge=1, le=200, description="单次返回条数（1-200）"),
):
    """
    按 publish_time 正序、游标分页返回本地已抓取的文章元数据（不含正文）。
    拿到 `id` 后配合 `/api/feed/article/{id}.md` 下载 markdown 正文。

    每次响应含 `next_since`（本批最后一篇的 publish_time），作为下次 `since`，
    循环调用直到 `articles` 为空即拉完；之后用保存的 `next_since` 做每日增量。
    """
    base = _base_url(request)
    rows = rss_store.get_feed_articles(since=since, fakeid=fakeid, limit=limit)
    subs = {s["fakeid"]: s.get("nickname", "") for s in rss_store.list_subscriptions()}

    items = []
    for a in rows:
        items.append({
            "id": a["id"],
            "fakeid": a["fakeid"],
            "nickname": subs.get(a["fakeid"], ""),
            "title": a.get("title", ""),
            "digest": a.get("digest", ""),
            "author": a.get("author", ""),
            "publish_time": a.get("publish_time", 0),
            "link": a.get("link", ""),
            "cover": proxy_image_url(a.get("cover", ""), base) if a.get("cover") else "",
            "content_fetched": bool(a.get("content")),
        })

    next_since = items[-1]["publish_time"] if items else since
    return {"articles": items, "next_since": next_since}


def _build_article_markdown(article: dict, nickname: str) -> str:
    """把 article['content']（HTML）转 markdown，加 YAML frontmatter。"""
    from markdownify import markdownify as md_convert

    md_body = md_convert(
        article.get("content", "") or "",
        heading_style="ATX",
        strip=["style", "script"],
        bullets="-",
    ).strip()

    # 可读日期（UTC+8）；publish_time 原始时间戳保留给程序用
    from datetime import datetime, timezone, timedelta
    pt = article.get('publish_time', 0) or 0
    date_str = (datetime.fromtimestamp(pt, timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
                if pt else "")

    # author 微信常缺失 → 回退成公众号名，保证字段不空
    fm_lines = [
        "---",
        f"title: {(article.get('title', '') or '').replace(chr(10), ' ')}",
        f"author: {article.get('author', '') or nickname}",
        f"nickname: {nickname}",
        f"fakeid: {article.get('fakeid', '')}",
        f"date: {date_str}",
        f"publish_time: {pt}",
        f"source_url: {article.get('link', '') or ''}",
        "---",
        "",
        f"# {article.get('title', '') or ''}",
        "",
    ]
    return "\n".join(fm_lines) + md_body + "\n"


def _safe_md_filename(title: str, article_id: int) -> str:
    """把文章标题转成安全的下载文件名（供 Content-Disposition 用）。"""
    name = (title or "").strip() or f"article_{article_id}"
    for ch in '/\\:*?"<>|\n\r\t':
        name = name.replace(ch, " ")
    name = " ".join(name.split())[:80].strip() or f"article_{article_id}"
    return name + ".md"


@router.get("/feed/article/{article_id:int}.md", summary="单篇文章 markdown 正文")
async def feed_article_md(article_id: int):
    """
    获取单篇文章的 markdown 正文，带 YAML frontmatter（title/author/nickname/fakeid/
    publish_time/source_url），图片走 `/api/image` 代理，Obsidian/Logseq 可直接渲染。

    状态码：200 正文 / 404 不存在 / 422 内容尚未抓取完成。
    浏览器与下载工具会按文章标题自动存为「标题.md」。
    """
    article = rss_store.get_article_by_id(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="文章不存在")
    if not article.get("content"):
        raise HTTPException(status_code=422, detail="文章内容尚未抓取完成，请稍后重试")

    sub = rss_store.get_subscription(article["fakeid"])
    nickname = (sub or {}).get("nickname", "") or ""

    md_payload = _build_article_markdown(article, nickname)
    filename = _safe_md_filename(article.get("title", ""), article_id)

    return PlainTextResponse(
        content=md_payload,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/feed/article/{article_id:int}.html", summary="单篇文章 HTML 正文")
async def feed_article_html(article_id: int):
    """获取单篇文章 HTML 文件，保留正文排版并带基础元信息。"""
    article = rss_store.get_article_by_id(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="文章不存在")
    if not article.get("content"):
        raise HTTPException(status_code=422, detail="文章内容尚未抓取完成，请稍后重试")

    from datetime import datetime, timezone, timedelta
    title = (article.get("title") or "无标题").strip()
    sub = rss_store.get_subscription(article["fakeid"])
    nickname = (sub or {}).get("nickname", "") or ""
    author = article.get("author") or nickname
    pt = article.get("publish_time", 0) or 0
    date_str = (datetime.fromtimestamp(pt, timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
                if pt else "")
    import html as html_module
    doc = "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
    doc += "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    doc += f"<title>{html_module.escape(title)}</title><style>"
    doc += "body{max-width:760px;margin:0 auto;padding:24px 18px;font:16px/1.8 -apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;color:#222}"
    doc += "h1{font-size:26px;line-height:1.4;margin:0 0 10px}.meta{color:#888;font-size:13px;margin-bottom:24px}.content img{max-width:100%;height:auto}.content{word-break:break-word}"
    doc += "</style></head><body>"
    doc += f"<h1>{html_module.escape(title)}</h1><div class='meta'>{html_module.escape(author)} · {html_module.escape(date_str)}"
    if article.get("link"):
        doc += f" · <a href='{html_module.escape(article['link'], quote=True)}' target='_blank' rel='noopener'>原文</a>"
    doc += f"</div><div class='content'>{article.get('content') or ''}</div></body></html>"
    filename = _safe_md_filename(title, article_id).removesuffix(".md") + ".html"
    return Response(content=doc, media_type="text/html; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})
