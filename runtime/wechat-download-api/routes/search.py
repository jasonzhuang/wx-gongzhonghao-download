#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从微信读书书架搜索公众号。"""

import os
from typing import Optional

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from utils.weread_client import WereadClient, WereadError, normalize_book_id

router = APIRouter()


class SearchResponse(BaseModel):
    success: bool
    data: Optional[dict] = None
    error: Optional[str] = None


def get_base_url(request: Request) -> str:
    site_url = os.getenv("SITE_URL", "").strip()
    if site_url:
        return site_url.rstrip("/")
    proto = request.headers.get("X-Forwarded-Proto", "http")
    host = request.headers.get("X-Forwarded-Host") or request.headers.get("Host", "localhost:5000")
    return f"{proto}://{host}"


async def searchbiz_raw(query: str, base_url: str = ""):
    """在微信读书已关注的公众号中搜索，保持旧调用方的返回契约。"""
    try:
        accounts = await WereadClient().list_mp_accounts()
    except WereadError as exc:
        return [], str(exc)

    needle = (query or "").strip().lower()
    if needle:
        accounts = [
            item for item in accounts
            if needle in str(item.get("nickname", "")).lower()
            or needle in str(item.get("alias", "")).lower()
            or needle in str(item.get("fakeid", "")).lower()
        ]

    # 支持直接粘贴 MP_WXS / 数字 / 旧 FakeID；仅当它确实在书架中时返回。
    if not accounts and needle:
        try:
            book_id = normalize_book_id(query)
            all_accounts = await WereadClient().list_mp_accounts()
            accounts = [item for item in all_accounts if item.get("fakeid") == book_id]
        except (ValueError, WereadError):
            pass
    return accounts[:20], None


@router.get("/searchbiz", response_model=SearchResponse, summary="搜索微信读书书架中的公众号")
async def search_accounts(
    query: str = Query(..., description="公众号名称、MP_WXS BookId 或旧 FakeID"),
    request: Request = None,
):
    accounts, err = await searchbiz_raw(query, get_base_url(request) if request else "")
    if err:
        return SearchResponse(success=False, error=err)
    return SearchResponse(success=True, data={"list": accounts, "total": len(accounts)})
