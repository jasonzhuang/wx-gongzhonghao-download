#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从微信读书书架返回公众号基础信息。"""

from typing import Dict, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from utils.weread_client import WereadClient, WereadError, normalize_book_id

router = APIRouter()


class AccountInfoResponse(BaseModel):
    success: bool
    data: Optional[Dict] = None
    error: Optional[str] = None


@router.get("/accountinfo", response_model=AccountInfoResponse, summary="获取微信读书公众号信息")
async def get_account_info(fakeid: str = Query(..., description="MP_WXS BookId（兼容旧 FakeID）")):
    try:
        book_id = normalize_book_id(fakeid)
        accounts = await WereadClient().list_mp_accounts()
        account = next((item for item in accounts if item.get("fakeid") == book_id), None)
        if not account:
            return AccountInfoResponse(success=False, error="微信读书书架中没有这个公众号")
        return AccountInfoResponse(success=True, data={
            "book_id": book_id,
            "nickname": account.get("nickname", ""),
            "author": account.get("alias", "公众号"),
            "cover": account.get("round_head_img", ""),
            "source": "weread-web",
        })
    except (WereadError, ValueError) as exc:
        return AccountInfoResponse(success=False, error=str(exc))
