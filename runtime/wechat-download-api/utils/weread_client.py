#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微信读书 Web 公众号接口客户端。

接口依据 tmwgsicp/wechat-download-api#23。文章列表在当前 Web 实现中还要求
x-wr-ticket 或 x-wrpa-0；它们可由登录续期接口响应头取得。这里集中处理
响应错误，不允许上层把认证失败误报成“0 篇新文章”。
"""

import base64
import html
import json
import re
import shlex
from typing import Dict, List, Optional, Tuple

import httpx

from utils.auth_manager import auth_manager


WEREAD_BASE = "https://weread.qq.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)


class WereadError(RuntimeError):
    pass


class WereadAuthError(WereadError):
    pass


def parse_curl_credentials(command: str) -> Dict[str, str]:
    """从浏览器“Copy as cURL”文本提取认证字段；只返回字段，不记录原文。"""
    result = {"cookie": "", "ticket": "", "wrpa": "", "vid": ""}
    text = (command or "").strip()
    if not text:
        return result
    try:
        tokens = shlex.split(text)
    except ValueError as exc:
        raise WereadAuthError(f"完整 cURL 解析失败: {exc}") from exc
    headers = {}
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in ("-H", "--header") and i + 1 < len(tokens):
            value = tokens[i + 1]
            key, sep, val = value.partition(":")
            if sep:
                headers[key.strip().lower()] = val.strip()
            i += 2
            continue
        if token in ("-b", "--cookie") and i + 1 < len(tokens):
            result["cookie"] = tokens[i + 1].strip()
            i += 2
            continue
        i += 1
    result["cookie"] = result["cookie"] or headers.get("cookie", "")
    result["ticket"] = headers.get("x-wr-ticket", "")
    result["wrpa"] = headers.get("x-wrpa-0", "")
    result["vid"] = headers.get("x-vid", "") or headers.get("x-wr-vid", "")
    return result


def normalize_book_id(identifier: str) -> str:
    """接受 MP_WXS、数字 ID 或旧 searchbiz fakeid，统一成微信读书 bookId。"""
    value = (identifier or "").strip()
    if value.startswith("MP_WXS_") and value[7:].isdigit():
        return value
    if value.isdigit():
        return f"MP_WXS_{value}"

    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = base64.b64decode(padded, validate=True).decode("ascii")
    except Exception as exc:
        raise ValueError(f"无法把公众号标识转换为微信读书 BookId: {value}") from exc
    if not decoded.isdigit():
        raise ValueError(f"公众号 FakeID 解码后不是数字: {value}")
    return f"MP_WXS_{decoded}"


def _error_code(data: Dict):
    for key in ("errCode", "errcode", "code"):
        if key in data:
            return data.get(key)
    return None


def _error_message(data: Dict) -> str:
    return str(
        data.get("errMsg") or data.get("errmsg") or data.get("message")
        or data.get("msg") or "未知错误"
    )


def _check_json(data: Dict, operation: str) -> Dict:
    if not isinstance(data, dict):
        raise WereadError(f"{operation}返回格式异常")
    code = _error_code(data)
    if code in (None, 0, "0"):
        return data
    msg = _error_message(data)
    if str(code) in {"-2041", "-2012", "-2001", "-1"}:
        raise WereadAuthError(
            f"{operation}认证失败: errCode={code}, {msg}；请重新登录并刷新文章列表凭证"
        )
    raise WereadError(f"{operation}失败: errCode={code}, {msg}")


def parse_mp_accounts(data: Dict) -> List[Dict]:
    """兼容 shelf/sync 中直接 bookInfo 与嵌套 bookInfo 两种结构。"""
    accounts = []
    seen = set()
    candidates = list(data.get("books") or [])
    mp_section = data.get("mp")
    if isinstance(mp_section, list):
        candidates.extend(mp_section)
    elif isinstance(mp_section, dict):
        candidates.extend(mp_section.get("books") or mp_section.get("items") or [])

    for item in candidates:
        if not isinstance(item, dict):
            continue
        info = item.get("bookInfo") if isinstance(item.get("bookInfo"), dict) else item
        book_id = str(info.get("bookId") or item.get("bookId") or "")
        if not book_id.startswith("MP_WXS_") or book_id in seen:
            continue
        seen.add(book_id)
        accounts.append({
            "fakeid": book_id,
            "book_id": book_id,
            "nickname": info.get("title") or info.get("bookName") or info.get("name") or book_id,
            "alias": info.get("author") or "公众号",
            "round_head_img": info.get("cover") or info.get("coverUrl") or "",
        })
    return accounts


def parse_mp_articles(
    data: Dict, book_id: str, offset: int = 0
) -> Tuple[List[Dict], Optional[int]]:
    """展开文章，并返回下一页游标；None 表示没有下一页。"""
    reviews = data.get("reviews") or []
    articles = []
    for group in reviews:
        if not isinstance(group, dict):
            continue
        for sub in group.get("subReviews") or []:
            if not isinstance(sub, dict):
                continue
            review = sub.get("review") if isinstance(sub.get("review"), dict) else sub
            info = review.get("mpInfo") if isinstance(review.get("mpInfo"), dict) else {}
            review_id = str(review.get("reviewId") or sub.get("reviewId") or "")
            original_id = str(info.get("originalId") or "")
            title = html.unescape(str(info.get("title") or "")).strip()
            if not review_id or not title:
                continue
            publish_time = int(
                info.get("time") or review.get("createTime")
                or group.get("createTime") or 0
            )
            link = (
                f"https://mp.weixin.qq.com/s/{original_id}" if original_id
                else f"https://weread.qq.com/web/mp/content?reviewId={review_id}"
            )
            articles.append({
                "aid": review_id,
                "review_id": review_id,
                "title": title,
                "link": link,
                "digest": html.unescape(str(info.get("content") or info.get("digest") or "")),
                "cover": info.get("pic_url") or info.get("picUrl") or "",
                "author": info.get("mp_name") or info.get("mpName") or "",
                "publish_time": publish_time,
                "book_id": book_id,
            })
    # synckey 是同步键，clearAll 也不是分页结束标志。
    # /web/mp/articles 的 offset 是 review group 的位置偏移。
    if not reviews:
        return articles, None
    return articles, max(0, int(offset)) + len(reviews)


class WereadClient:
    def __init__(self, credentials: Optional[Dict] = None):
        self.credentials = credentials or auth_manager.get_credentials()
        if not self.credentials or not self.credentials.get("cookie"):
            raise WereadAuthError("未配置微信读书 Cookie")

    def _headers(self, html_response: bool = False) -> Dict[str, str]:
        headers = {
            "Accept": "text/html,*/*" if html_response else "application/json, text/plain, */*",
            "Referer": "https://weread.qq.com/",
            "Origin": "https://weread.qq.com",
            "User-Agent": USER_AGENT,
            "Cookie": self.credentials.get("cookie", ""),
        }
        ticket = self.credentials.get("ticket", "")
        if ticket:
            headers["x-wr-ticket"] = ticket
        wrpa = self.credentials.get("wrpa", "")
        if wrpa:
            headers["x-wrpa-0"] = wrpa
        return headers

    @staticmethod
    def _merge_cookie_header(cookie_header: str, response) -> str:
        cookies: Dict[str, str] = {}
        for part in (cookie_header or "").split(";"):
            key, sep, value = part.strip().partition("=")
            if sep and key:
                cookies[key] = value
        for key, value in response.cookies.items():
            cookies[key] = value
        return "; ".join(f"{key}={value}" for key, value in cookies.items())

    async def renew_mp_auth(self) -> Dict:
        """续期 Cookie，并从响应头取得文章列表所需的 WPA 凭证。"""
        headers = self._headers()
        headers["Content-Type"] = "application/json;charset=UTF-8"
        payloads = (
            {"rq": "%2Fweb%2Fbook%2Fread", "ql": False},
            {"rq": "%2Fweb%2Fbook%2Fread", "ql": True},
            {"rq": "%2Fweb%2Fbook%2Fread"},
        )
        errors = []
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            for payload in payloads:
                try:
                    # 与 Web 客户端保持紧凑 JSON 形式，部分网关对 body 形态敏感。
                    response = await client.post(
                        WEREAD_BASE + "/web/login/renewal",
                        content=json.dumps(payload, separators=(",", ":")),
                        headers=headers,
                    )
                    response.raise_for_status()
                    try:
                        data = _check_json(response.json(), "续期微信读书登录")
                    except ValueError as exc:
                        raise WereadAuthError("微信读书续期接口返回非 JSON") from exc
                    if data.get("succ") not in (None, 1, True):
                        raise WereadAuthError(
                            f"微信读书续期失败: succ={data.get('succ')}"
                        )

                    self.credentials["cookie"] = self._merge_cookie_header(
                        self.credentials.get("cookie", ""), response
                    )
                    ticket = response.headers.get("x-wr-ticket", "").strip()
                    wrpa = response.headers.get("x-wrpa-0", "").strip()
                    if ticket:
                        self.credentials["ticket"] = ticket
                    if wrpa:
                        self.credentials["wrpa"] = wrpa
                    self.credentials["vid"] = (
                        self.credentials.get("vid")
                        or auth_manager._vid_from_cookie(self.credentials["cookie"])
                    )
                    if self.credentials.get("ticket") or self.credentials.get("wrpa"):
                        return dict(self.credentials)
                except Exception as exc:
                    errors.append(str(exc))

        if not (self.credentials.get("ticket") or self.credentials.get("wrpa")):
            detail = "；".join(dict.fromkeys(errors[-3:])) if errors else "响应头没有文章列表凭证"
            raise WereadAuthError(f"微信读书续期失败（已尝试 3 种请求格式）: {detail}")
        return dict(self.credentials)

    async def _get_json(self, path: str, params: Dict, operation: str) -> Dict:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(
                WEREAD_BASE + path, params=params, headers=self._headers()
            )
            response.raise_for_status()
            try:
                data = response.json()
            except ValueError as exc:
                raise WereadAuthError(f"{operation}返回非 JSON，微信读书登录态可能已失效") from exc
        return _check_json(data, operation)

    async def check_auth(self) -> Dict:
        data = await self._get_json(
            "/web/shelf/sync",
            {"userVid": self.credentials.get("vid", ""), "synckey": 0},
            "校验微信读书登录",
        )
        accounts = parse_mp_accounts(data)
        if not accounts:
            raise WereadError("微信读书书架中没有公众号；请先在微信读书 App 关注至少一个公众号")
        # shelf/sync 只能校验 Cookie；再读一页文章，确保 WPA 凭证也有效。
        articles, _ = await self.list_articles(accounts[0]["fakeid"], 0)
        return {"account_count": len(accounts), "probe_article_count": len(articles)}

    async def list_mp_accounts(self) -> List[Dict]:
        data = await self._get_json(
            "/web/shelf/sync",
            {"userVid": self.credentials.get("vid", ""), "synckey": 0},
            "读取微信读书书架",
        )
        return parse_mp_accounts(data)

    async def list_articles(
        self, identifier: str, offset: int = 0
    ) -> Tuple[List[Dict], Optional[int]]:
        book_id = normalize_book_id(identifier)
        data = await self._get_json(
            "/web/mp/articles",
            {"bookId": book_id, "offset": max(0, int(offset))},
            f"读取 {book_id} 文章列表",
        )
        return parse_mp_articles(data, book_id, offset=offset)

    async def fetch_content(self, review_id: str) -> str:
        if not review_id:
            raise WereadError("缺少 reviewId，无法获取正文")
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(
                WEREAD_BASE + "/web/mp/content",
                params={"reviewId": review_id},
                headers=self._headers(html_response=True),
            )
            response.raise_for_status()
            text = response.text
        content_type = response.headers.get("content-type", "")
        if "json" in content_type or text.lstrip().startswith("{"):
            try:
                _check_json(response.json(), "获取微信读书文章正文")
            except ValueError:
                pass
            raise WereadError("微信读书正文接口返回了异常 JSON")
        if not re.search(r'id=["\']js_content["\']|rich_media_content', text, re.I):
            raise WereadError("微信读书正文响应中没有文章内容容器")
        return text


weread_client_factory = WereadClient
