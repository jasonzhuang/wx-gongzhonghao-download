"""
开源版（单用户 / SQLite）的 MCP 数据适配层。

把 6 个 MCP tool 需要的能力桥接到 utils.rss_store（sqlite3）+ 搜索/凭证。
与 SaaS 版的多租户 SQLAlchemy 适配层不同：单用户、无 user_id、无付费门禁。
"""
import os
import logging

from utils import rss_store
from utils.image_proxy import proxy_image_url
from utils.weread_client import WereadClient, WereadError, normalize_book_id

logger = logging.getLogger(__name__)

def _base_url() -> str:
    return os.getenv("SITE_URL", "").rstrip("/")


class StoreAdapter:
    """单用户数据适配：全部同步 sqlite 读，MCP 调用稀疏，直接调用即可。"""

    async def list_subscriptions(self) -> list[dict]:
        subs = rss_store.list_subscriptions()
        base = _base_url()
        return [{
            "fakeid": s.get("fakeid", ""),
            "nickname": s.get("nickname", ""),
            "alias": s.get("alias", ""),
            "head_img": proxy_image_url(s.get("head_img", ""), base) if s.get("head_img") else "",
            "article_count": s.get("article_count", 0),
            "category": s.get("category_name", ""),
            "created_at": s.get("created_at", 0),
        } for s in subs]

    async def search_accounts(self, query: str) -> list[dict]:
        try:
            accounts = await WereadClient().list_mp_accounts()
        except WereadError as exc:
            raise RuntimeError(str(exc)) from exc
        blacklisted = set(rss_store.get_active_blacklist_fakeids())
        needle = (query or "").strip().lower()
        out = []
        for a in accounts:
            fid = a.get("fakeid", "")
            if fid in blacklisted or not (
                needle in a.get("nickname", "").lower()
                or needle in a.get("alias", "").lower()
                or needle in fid.lower()
            ):
                continue
            out.append({
                "fakeid": fid,
                "nickname": a.get("nickname", ""),
                "alias": a.get("alias", ""),
                "service_type": "weread-mp",
            })
        return out

    async def get_recent_articles(self, since: int, limit: int, source_id: str | None) -> dict:
        arts = rss_store.get_feed_articles(since=since, fakeid=source_id or None, limit=limit)
        items = [{
            "id": a.get("id"),
            "title": a.get("title", ""),
            "digest": a.get("digest", ""),
            "author": a.get("author", ""),
            "fakeid": a.get("fakeid", ""),
            "publish_time": a.get("publish_time", 0),
            "link": a.get("link", ""),
            "content_fetched": bool(a.get("content")),
        } for a in arts]
        next_since = arts[-1].get("publish_time", since) if arts else since
        return {"articles": items, "next_since": next_since}

    async def read_article(self, article_id: int) -> str:
        from routes.feed import _build_article_markdown
        art = rss_store.get_article_by_id(article_id)
        if not art:
            raise ValueError(f"文章 {article_id} 不存在")
        if not art.get("content"):
            raise ValueError("文章正文尚未抓取完成，稍后重试")
        sub = rss_store.get_subscription(art.get("fakeid", ""))
        nickname = (sub or {}).get("nickname", "") or art.get("author", "")
        return _build_article_markdown(art, nickname)

    async def subscribe_account(self, fakeid: str) -> dict:
        try:
            book_id = normalize_book_id(fakeid)
            accounts = await WereadClient().list_mp_accounts()
        except (WereadError, ValueError) as exc:
            raise ValueError(str(exc)) from exc
        account = next((item for item in accounts if item.get("fakeid") == book_id), None)
        if not account:
            raise ValueError("微信读书书架中没有这个公众号，请先在微信读书 App 中关注")
        fakeid = book_id
        if rss_store.is_blacklisted(fakeid):
            raise ValueError("该公众号已被标记失效，无法订阅")
        if rss_store.get_subscription(fakeid):
            return {"success": True, "message": "已订阅，无需重复"}
        nickname = account.get("nickname", "")
        rss_store.add_subscription(
            fakeid, nickname=nickname, alias=account.get("alias", ""),
            head_img=account.get("round_head_img", ""),
        )
        return {"success": True, "message": f"已订阅 {nickname or fakeid}"}

    async def unsubscribe_account(self, fakeid: str) -> dict:
        ok = rss_store.remove_subscription(fakeid)
        return {"success": ok, "message": "已取消订阅" if ok else "未找到该订阅"}
