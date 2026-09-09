#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (C) 2026 tmwgsicp
# Licensed under the GNU Affero General Public License v3.0
# See LICENSE file in the project root for full license text.
# SPDX-License-Identifier: AGPL-3.0-only
"""
管理路由 - FastAPI版本
"""

import time
import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List
from utils.auth_manager import auth_manager
from utils.weread_client import WereadClient
from utils import rss_store

router = APIRouter()
_history_fetch_lock = asyncio.Lock()


# ── 状态管理 ─────────────────────────────────────────────

class StatusResponse(BaseModel):
    """状态响应模型"""
    authenticated: bool
    loggedIn: bool
    account: str
    nickname: Optional[str] = ""
    fakeid: Optional[str] = ""
    expireTime: Optional[int] = 0
    isExpired: Optional[bool] = False
    status: str


@router.get("/status", response_model=StatusResponse, summary="获取登录状态")
async def get_status():
    """获取当前登录状态，并在线校验已保存的微信读书凭证。"""
    status = auth_manager.get_status()
    if not status.get("authenticated"):
        return status

    # get_status() 只能说明本地配置存在，不能说明 Cookie/WPA 仍然有效。
    # 管理页的“刷新”应触发真实校验，避免把已过期凭证显示为在线。
    try:
        check = await WereadClient().check_auth()
    except Exception as exc:
        status.update({
            "authenticated": False,
            "loggedIn": False,
            "isExpired": True,
            "status": str(exc),
        })
        return status

    status.update({
        "authenticated": True,
        "loggedIn": True,
        "isExpired": False,
        "status": f"微信读书登录有效，发现 {check.get('account_count', 0)} 个公众号",
    })
    return status


@router.post("/logout", summary="退出登录")
async def logout():
    """退出登录，清除凭证"""
    success = auth_manager.clear_credentials()
    if success:
        return {"success": True, "message": "已退出登录"}
    else:
        return {"success": False, "message": "退出登录失败"}


# ── 黑名单管理 ─────────────────────────────────────────────

class BlacklistItem(BaseModel):
    id: int
    fakeid: str
    nickname: str
    reason: str
    verification_count: int
    is_active: bool
    blacklisted_at: int
    unblacklisted_at: Optional[int]
    note: str


class AddBlacklistRequest(BaseModel):
    fakeid: str = Field(..., description="公众号ID")
    nickname: str = Field("", description="公众号名称")
    reason: str = Field("manual", description="加入原因")
    note: str = Field("", description="备注")


@router.get("/blacklist", summary="获取黑名单列表")
async def get_blacklist():
    """获取公众号黑名单列表"""
    blacklist = rss_store.get_blacklist()
    return {
        "blacklist": [
            BlacklistItem(
                id=bl["id"],
                fakeid=bl["fakeid"],
                nickname=bl["nickname"],
                reason=bl["reason"],
                verification_count=bl["verification_count"],
                is_active=bool(bl["is_active"]),
                blacklisted_at=bl["blacklisted_at"],
                unblacklisted_at=bl["unblacklisted_at"],
                note=bl["note"],
            )
            for bl in blacklist
        ]
    }


@router.post("/blacklist", summary="添加到黑名单")
async def add_to_blacklist(req: AddBlacklistRequest):
    """手动添加公众号到黑名单"""
    success = rss_store.add_to_blacklist(
        fakeid=req.fakeid,
        nickname=req.nickname,
        reason=req.reason,
        note=req.note or "手动添加"
    )
    if success:
        return {"success": True, "message": f"已将 {req.nickname or req.fakeid} 加入黑名单"}
    return {"success": False, "message": "添加失败"}


@router.delete("/blacklist/{fakeid}", summary="从黑名单移除")
async def remove_from_blacklist(fakeid: str):
    """从黑名单移除公众号（标记为非活跃）"""
    success = rss_store.remove_from_blacklist(fakeid)
    if success:
        return {"success": True, "message": "已从黑名单移除"}
    return {"success": False, "message": "移除失败，记录不存在"}


@router.delete("/blacklist/record/{blacklist_id}", summary="永久删除黑名单记录")
async def delete_blacklist_record(blacklist_id: int):
    """永久删除黑名单记录（仅可删除非活跃记录）"""
    success = rss_store.delete_blacklist_record(blacklist_id)
    if success:
        return {"success": True, "message": "记录已删除"}
    return {"success": False, "message": "删除失败，记录不存在或仍在生效中"}


# ── 分类管理 ─────────────────────────────────────────────

class CategoryItem(BaseModel):
    id: int
    name: str
    description: str
    color: str
    sort_order: int
    subscription_count: int
    created_at: int


class CreateCategoryRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="分类名称")
    description: str = Field("", max_length=200, description="分类描述")
    color: str = Field("blue", description="颜色: blue, green, red, purple, orange, gray")


class UpdateCategoryRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    description: Optional[str] = None
    color: Optional[str] = None


class SetCategoryRequest(BaseModel):
    category_id: Optional[int] = Field(None, description="分类ID，null表示取消分类")


@router.get("/categories", summary="获取分类列表")
async def get_categories():
    """获取所有分类"""
    categories = rss_store.list_categories()
    return {
        "categories": [
            CategoryItem(
                id=c["id"],
                name=c["name"],
                description=c["description"],
                color=c["color"],
                sort_order=c["sort_order"],
                subscription_count=c["subscription_count"],
                created_at=c["created_at"],
            )
            for c in categories
        ]
    }


@router.post("/categories", summary="创建分类")
async def create_category(req: CreateCategoryRequest):
    """创建新分类"""
    category_id = rss_store.create_category(
        name=req.name,
        description=req.description,
        color=req.color
    )
    if category_id:
        return {"success": True, "id": category_id, "message": f"分类 '{req.name}' 创建成功"}
    raise HTTPException(status_code=400, detail="分类名称已存在")


@router.patch("/categories/{category_id}", summary="更新分类")
async def update_category(category_id: int, req: UpdateCategoryRequest):
    """更新分类信息"""
    success = rss_store.update_category(
        category_id=category_id,
        name=req.name,
        description=req.description,
        color=req.color
    )
    if success:
        return {"success": True, "message": "分类已更新"}
    raise HTTPException(status_code=404, detail="分类不存在")


@router.delete("/categories/{category_id}", summary="删除分类")
async def delete_category(category_id: int):
    """删除分类（订阅会自动解除关联）"""
    success = rss_store.delete_category(category_id)
    if success:
        return {"success": True, "message": "分类已删除"}
    raise HTTPException(status_code=404, detail="分类不存在")


@router.get("/categories/{category_id}/subscriptions", summary="获取分类下的订阅")
async def get_category_subscriptions(category_id: int):
    """获取分类下的所有订阅"""
    category = rss_store.get_category(category_id)
    if not category:
        raise HTTPException(status_code=404, detail="分类不存在")
    
    subscriptions = rss_store.get_subscriptions_by_category(category_id)
    return {
        "category": CategoryItem(
            id=category["id"],
            name=category["name"],
            description=category["description"],
            color=category["color"],
            sort_order=category["sort_order"],
            subscription_count=len(subscriptions),
            created_at=category["created_at"],
        ),
        "subscriptions": subscriptions
    }


@router.put("/subscriptions/{fakeid}/category", summary="设置订阅分类")
async def set_subscription_category(fakeid: str, req: SetCategoryRequest):
    """设置订阅的分类"""
    # 如果指定了分类，验证分类存在
    if req.category_id is not None:
        category = rss_store.get_category(req.category_id)
        if not category:
            raise HTTPException(status_code=404, detail="分类不存在")
    
    success = rss_store.set_subscription_category(fakeid, req.category_id)
    if success:
        return {"success": True, "message": "分类已设置"}
    raise HTTPException(status_code=404, detail="订阅不存在")


# ── 历史文章获取 ─────────────────────────────────────────────

class FetchHistoryRequest(BaseModel):
    fakeid: str = Field(..., description="公众号ID")
    count: int = Field(1, ge=1, le=100, description="获取数量，1-100篇")
    until: int = Field(0, ge=0, description="可选：抓取到该时间戳为止，0表示按数量获取")
    before: int = Field(0, ge=0, description="可选：时间范围终点，0表示当前时间")
    max_articles: int = Field(0, ge=0, le=1000, description="可选：范围文章超过该数量时只统计，不补抓正文")


class FetchHistoryResponse(BaseModel):
    success: bool
    message: str
    fetched_count: int = 0
    new_count: int = 0
    has_more: bool = True
    matched_count: int = 0
    content_count: int = 0
    oldest_time: int = 0
    newest_time: int = 0
    exportable_count: int = 0
    content_failed_count: int = 0
    batch_required: bool = False


@router.post("/history/fetch", response_model=FetchHistoryResponse, summary="获取历史文章")
async def fetch_history_articles(req: FetchHistoryRequest):
    """
    从微信读书文章列表分页获取历史文章，并补齐正文后存入数据库。
    """
    # 检查登录状态
    status = auth_manager.get_status()
    if not status.get("authenticated"):
        return FetchHistoryResponse(
            success=False,
            message="未配置微信读书 Cookie/Ticket，请先打开登录配置页",
            fetched_count=0,
            new_count=0
        )
    
    # 检查订阅是否存在
    subscriptions = rss_store.list_subscriptions()
    sub = next((s for s in subscriptions if s["fakeid"] == req.fakeid), None)
    if not sub:
        return FetchHistoryResponse(
            success=False,
            message="订阅不存在，请先添加订阅",
            fetched_count=0,
            new_count=0
        )
    if req.until and req.before and req.until > req.before:
        return FetchHistoryResponse(
            success=False,
            message="时间范围无效：开始时间不能晚于结束时间",
        )
    
    try:
        # 同一公众号的历史游标必须串行推进，避免重复请求同一页。
        async with _history_fetch_lock:
            fetched_count, new_count, has_more, matched_count, content_count, oldest_time, newest_time, content_failed_count, batch_required = await _fetch_history_internal(
                fakeid=req.fakeid,
                target_count=req.count,
                until=req.until,
                before=req.before,
                max_articles=req.max_articles,
            )
        exportable_count = rss_store.count_export_articles(
            req.fakeid, since=req.until, before=req.before or int(time.time())
        ) if req.until else 0

        message = (
            f"所选范围共 {matched_count} 篇，超过单次建议上限 {req.max_articles} 篇，请缩小时间范围分批导出"
            if batch_required else
            f"获取完成，共获取 {fetched_count} 篇，新增 {new_count} 篇"
        )
        
        return FetchHistoryResponse(
            success=True,
            message=message,
            fetched_count=fetched_count,
            new_count=new_count,
            has_more=has_more,
            matched_count=matched_count,
            content_count=content_count,
            oldest_time=oldest_time,
            newest_time=newest_time,
            exportable_count=exportable_count,
            content_failed_count=content_failed_count,
            batch_required=batch_required,
        )
    except Exception as e:
        return FetchHistoryResponse(
            success=False,
            message=f"获取失败: {str(e)}",
            fetched_count=0,
            new_count=0
        )


async def _fetch_history_internal(fakeid: str, target_count: int, until: int = 0,
                                  before: int = 0, max_articles: int = 0) -> tuple:
    """分页读取历史文章，返回数量、正文状态、时间范围和是否还有更早文章。"""
    from utils.rss_poller import rss_poller
    from utils.weread_client import WereadClient

    if not rss_store.get_subscription(fakeid):
        raise ValueError("订阅不存在")
    if until and before and until > before:
        raise ValueError("时间范围无效：开始时间不能晚于结束时间")

    client = WereadClient()
    cursor = rss_store.get_history_cursor(fakeid)
    # 带时间范围的导出必须重新确认真实范围，不能信任旧版本可能错误写入的 complete 标记。
    # 这样即使旧版本已经把游标标成完成，也不会阻止半年/一年导出继续向前扫描。
    if cursor["complete"] and not until:
        return 0, 0, False, 0, 0, 0, 0, 0, False

    historical_articles = []
    offset = 0 if until else cursor["offset"]
    # 兼容旧版本：已有历史缓存但没有游标时，从已缓存最早文章附近继续。
    if offset == 0 and not until:
        offset = rss_store.get_oldest_historical_publish_time(fakeid)
    next_offset = None
    range_complete = not until
    for _ in range(200):
        page, next_offset = await client.list_articles(fakeid, offset)
        historical_articles.extend(page)
        oldest_in_page = min(
            (int(item.get("publish_time") or 0) for item in page),
            default=0,
        )
        if not until and len(historical_articles) >= target_count:
            break
        if until and oldest_in_page and oldest_in_page <= until:
            range_complete = True
            break
        if next_offset is None or next_offset == offset:
            range_complete = True
            break
        offset = next_offset
        await asyncio.sleep(2)

    if until and not range_complete:
        raise ValueError("历史文章超过分页扫描上限，尚未到达所选时间边界；已停止导出以避免生成不完整文件")

    # 不能截断最后一页：微信读书游标按整页推进，截断会丢掉同页中尚未保存的文章。
    # 因此实际获取量可能略大于 target_count，但不会跳过历史文章。
    if not historical_articles and next_offset is None:
        rss_store.update_history_cursor(fakeid, None, complete=True)
        return 0, 0, False, 0, 0, 0, 0, 0, False

    # 只保存请求时间范围内的文章；边界所在页面可能同时包含更早文章。
    if until:
        historical_articles = [
            item for item in historical_articles
            if int(item.get("publish_time") or 0) >= until
            and (not before or int(item.get("publish_time") or 0) <= before)
        ]
    # 同一篇文章可能同时出现在轮询结果和历史扫描结果中，或因边界游标重复出现。
    unique_articles = []
    seen_articles = set()
    for item in historical_articles:
        key = item.get("link") or item.get("review_id") or item.get("aid")
        if key and key in seen_articles:
            continue
        if key:
            seen_articles.add(key)
        unique_articles.append(item)
    historical_articles = unique_articles
    timestamps = [int(item.get("publish_time") or 0) for item in historical_articles if item.get("publish_time")]
    matched_count = len(historical_articles)
    oldest_time = min(timestamps, default=0)
    newest_time = max(timestamps, default=0)

    # 先保存完整元数据，再只抓尚无正文的文章，避免每次范围扫描重复请求已有正文。
    new_count = rss_store.save_articles(fakeid, historical_articles, source="deep_fetch")
    batch_required = bool(max_articles and matched_count > max_articles)
    if batch_required:
        # 导出预检已经确认范围过大时，不继续抓正文或生成大文件；元数据仍保留，
        # 用户缩小日期范围后无需担心列表漏项。
        rss_store.update_history_cursor(
            fakeid,
            next_offset,
            complete=next_offset is None or next_offset == offset,
        )
        return (
            matched_count, new_count,
            next_offset is not None and next_offset != offset,
            matched_count, 0, oldest_time, newest_time, 0, True,
        )
    existing = rss_store.get_export_articles(
        fakeid, since=until, before=before or int(time.time()), limit=3000
    )
    content_links = {item.get("link") for item in existing if item.get("link")}
    pending = [
        item for item in historical_articles
        if item.get("link") not in content_links
    ]
    failed_items = []
    content_count = 0
    # 小批量补正文并逐批落库。即使中途超时，已完成批次也不会丢失。
    batch_size = 10
    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        remaining = batch
        for attempt in range(3):
            if not remaining:
                break
            enriched, _ = await rss_poller._enrich_articles_content(remaining, client)
            rss_store.save_articles(fakeid, enriched, source="deep_fetch")
            remaining = [item for item in enriched if not item.get("content")]
            if remaining and attempt < 2:
                await asyncio.sleep(2)
        content_count += len(batch) - len(remaining)
        failed_items.extend(remaining)
    rss_store.update_history_cursor(
        fakeid,
        next_offset,
        complete=next_offset is None or next_offset == offset,
    )
    content_failed_count = len(failed_items)
    return (
        matched_count, new_count,
        next_offset is not None and next_offset != offset,
        matched_count, content_count, oldest_time, newest_time, content_failed_count,
        batch_required,
    )
