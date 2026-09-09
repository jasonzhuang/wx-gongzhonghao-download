#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微信读书公众号文章列表 API。"""

from typing import Dict, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from utils.weread_client import WereadClient, WereadError

router = APIRouter()


class ArticlesResponse(BaseModel):
    success: bool
    data: Optional[Dict] = None
    error: Optional[str] = None


@router.get("/articles", response_model=ArticlesResponse, summary="获取微信读书公众号文章列表")
async def get_articles(
    fakeid: str = Query(..., description="公众号 MP_WXS BookId（兼容旧 FakeID）"),
    begin: int = Query(0, ge=0, alias="begin", description="微信读书文章列表游标"),
    count: int = Query(10, ge=1, le=100),
    keyword: Optional[str] = Query(None, description="在本次分页结果中筛选标题/摘要"),
):
    try:
        client = WereadClient()
        articles = []
        offset = begin
        next_offset = None
        for _ in range(10):
            page, next_offset = await client.list_articles(fakeid, offset)
            if keyword:
                needle = keyword.lower()
                page = [
                    item for item in page
                    if needle in item.get("title", "").lower()
                    or needle in item.get("digest", "").lower()
                ]
            articles.extend(page)
            if len(articles) >= count or next_offset is None or next_offset == offset:
                break
            offset = next_offset
        articles = articles[:count]
        public_items = [{
            "aid": item.get("aid", ""),
            "title": item.get("title", ""),
            "link": item.get("link", ""),
            "update_time": item.get("publish_time", 0),
            "create_time": item.get("publish_time", 0),
            "digest": item.get("digest", ""),
            "cover": item.get("cover", ""),
            "author": item.get("author", ""),
        } for item in articles]
        return ArticlesResponse(success=True, data={
            "articles": public_items,
            "total": None,
            "begin": begin,
            "next_begin": next_offset,
            "count": len(public_items),
            "keyword": keyword,
            "source": "weread-web",
        })
    except (WereadError, ValueError) as exc:
        return ArticlesResponse(success=False, error=str(exc))
    except Exception as exc:
        return ArticlesResponse(success=False, error=f"读取文章列表失败: {exc}")


@router.get("/articles/search", response_model=ArticlesResponse, summary="筛选公众号文章")
async def search_articles(
    fakeid: str = Query(...),
    query: str = Query(..., alias="query"),
    begin: int = Query(0, ge=0, alias="begin"),
    count: int = Query(10, ge=1, le=100),
):
    return await get_articles(fakeid=fakeid, keyword=query, begin=begin, count=count)
