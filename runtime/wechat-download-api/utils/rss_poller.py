#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基于微信读书 Web 的 RSS 后台轮询器。"""

import asyncio
import logging
import os
from typing import Dict, List, Optional, Tuple

from utils import rss_store
from utils.content_processor import process_article_content
from utils.weread_client import WereadClient, WereadError

logger = logging.getLogger(__name__)

POLL_INTERVAL = int(os.getenv("RSS_POLL_INTERVAL", "7200"))
ARTICLES_PER_POLL = int(os.getenv("ARTICLES_PER_POLL", "10"))
FETCH_FULL_CONTENT = os.getenv("RSS_FETCH_FULL_CONTENT", "true").lower() == "true"
CONTENT_CONCURRENCY = max(1, int(os.getenv("RSS_CONTENT_CONCURRENCY", "2")))


class RSSPoller:
    _instance = None
    _task: Optional[asyncio.Task] = None
    _running = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._last_result = {
                "message": "尚未执行轮询", "ok": 0, "failed": 0,
                "fetched": 0, "saved": 0, "content_failed": 0, "errors": [],
            }
            cls._instance._poll_lock = asyncio.Lock()
        return cls._instance

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("WeRead RSS poller started (interval=%ds)", POLL_INTERVAL)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("WeRead RSS poller stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_result(self) -> Dict:
        return dict(self._last_result)

    async def _loop(self):
        while self._running:
            try:
                await self.poll_now()
            except Exception as exc:
                logger.error("RSS poll cycle fatal error: %s", exc, exc_info=True)
            await asyncio.sleep(POLL_INTERVAL)

    async def _poll_all(self, fakeids: Optional[List[str]] = None) -> Dict:
        fakeids = list(fakeids) if fakeids is not None else rss_store.get_all_fakeids()
        result = {
            "ok": 0, "failed": 0, "fetched": 0, "saved": 0,
            "content_failed": 0, "errors": [], "message": "",
        }
        if not fakeids:
            result["message"] = "没有订阅，无需轮询"
            self._last_result = result
            return result

        try:
            client = WereadClient()
        except WereadError as exc:
            result.update(failed=len(fakeids), errors=[str(exc)], message=str(exc))
            self._last_result = result
            return result

        blacklisted = set(rss_store.get_active_blacklist_fakeids())
        active_fakeids = [fid for fid in fakeids if fid not in blacklisted]
        for fakeid in active_fakeids:
            try:
                articles, _ = await client.list_articles(fakeid, 0)
                articles = articles[:ARTICLES_PER_POLL]
                result["fetched"] += len(articles)

                content_errors = []
                if articles and FETCH_FULL_CONTENT:
                    articles, content_errors = await self._enrich_articles_content(articles, client)
                    result["content_failed"] += len(content_errors)

                if articles:
                    result["saved"] += rss_store.save_articles(fakeid, articles, source="poll")
                rss_store.update_last_poll(fakeid)
                result["ok"] += 1

                if content_errors:
                    message = f"{fakeid[:16]}: {len(content_errors)} 篇正文失败"
                    result["errors"].append(message)
                    logger.warning(message)
            except Exception as exc:
                result["failed"] += 1
                message = f"{fakeid[:16]}: {exc}"
                result["errors"].append(message)
                logger.error("RSS poll failed: %s", message)
            await asyncio.sleep(2)

        skipped = len(fakeids) - len(active_fakeids)
        if skipped:
            result["errors"].append(f"黑名单跳过 {skipped} 个订阅")
        result["message"] = (
            f"轮询结束：成功 {result['ok']} 个，失败 {result['failed']} 个，"
            f"取得 {result['fetched']} 篇，正文失败 {result['content_failed']} 篇"
        )
        self._last_result = result
        return result

    async def _enrich_articles_content(
        self, articles: List[Dict], client: Optional[WereadClient] = None
    ) -> Tuple[List[Dict], List[str]]:
        client = client or WereadClient()
        semaphore = asyncio.Semaphore(CONTENT_CONCURRENCY)
        site_url = os.getenv("SITE_URL", "http://localhost:5000").rstrip("/")
        errors: List[str] = []

        async def enrich(article: Dict) -> Dict:
            review_id = article.get("review_id") or article.get("aid") or ""
            async with semaphore:
                try:
                    raw_html = await client.fetch_content(review_id)
                    parsed = process_article_content(raw_html, proxy_base_url=site_url)
                    content = parsed.get("content", "")
                    if not content:
                        raise WereadError("正文解析为空")
                    article["content"] = content
                    article["plain_content"] = parsed.get("plain_content", "")
                except Exception as exc:
                    errors.append(f"{review_id}: {exc}")
                await asyncio.sleep(1)
            return article

        enriched = await asyncio.gather(*(enrich(dict(item)) for item in articles))
        return list(enriched), errors

    async def poll_now(self) -> Dict:
        async with self._poll_lock:
            return await self._poll_all()

    async def poll_subscription(self, fakeid: str) -> Dict:
        """立即轮询单个已订阅公众号。"""
        async with self._poll_lock:
            return await self._poll_all([fakeid])


rss_poller = RSSPoller()
