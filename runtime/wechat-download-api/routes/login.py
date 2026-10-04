#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微信读书 Cookie/WPA 配置、自动续期与在线校验。"""

import json
import logging
import time
import uuid
from typing import Dict, Optional
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from utils.auth_manager import auth_manager
from utils.weread_client import WereadClient, WereadError, parse_curl_credentials
from utils.webhook import webhook

logger = logging.getLogger(__name__)

router = APIRouter()

WEREAD_BASE = "https://weread.qq.com"
_QR_SESSIONS: Dict[str, Dict] = {}
_QR_SESSION_TTL = 10 * 60


def _cleanup_qr_sessions() -> None:
    now = time.time()
    for key, value in list(_QR_SESSIONS.items()):
        if now - value["created_at"] > _QR_SESSION_TTL:
            client = value.get("client")
            if client:
                # 关闭动作在下次请求中异步完成；过期会话不会再被使用。
                value["closed"] = True
            _QR_SESSIONS.pop(key, None)


def _cookie_header(client: httpx.AsyncClient) -> str:
    values = {}
    for cookie in client.cookies.jar:
        values[cookie.name] = cookie.value
    return "; ".join(f"{name}={value}" for name, value in values.items())


def _qr_svg(url: str) -> str:
    """使用已有的 reportlab 生成本地 SVG，避免把登录 UID 交给第三方二维码服务。"""
    try:
        from reportlab.graphics import renderSVG
        from reportlab.graphics.barcode.qr import QrCodeWidget
        from reportlab.graphics.shapes import Drawing
    except ImportError as exc:
        raise RuntimeError("当前环境缺少二维码生成依赖 reportlab") from exc
    qr = QrCodeWidget(url)
    x0, y0, x1, y1 = qr.getBounds()
    drawing = Drawing(x1 - x0, y1 - y0)
    drawing.add(qr)
    return renderSVG.drawToString(drawing)


def _web_json_succeeded(response) -> bool:
    """微信读书业务错误也会返回 HTTP 200，必须同时校验 JSON errCode。"""
    if not 200 <= int(response.status_code) < 300:
        return False
    try:
        data = response.json()
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    code = data.get("errCode", data.get("errcode"))
    return code in (None, 0, "0")


async def _new_qr_session() -> Dict:
    _cleanup_qr_sessions()
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(70.0, connect=20.0),
        follow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/150 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
        },
    )
    try:
        await client.get(f"{WEREAD_BASE}/r/weread-skills", headers={"Referer": f"{WEREAD_BASE}/"})
        response = await client.get(
            f"{WEREAD_BASE}/api/auth/getLoginUid",
            headers={"Referer": f"{WEREAD_BASE}/r/weread-skills"},
        )
        response.raise_for_status()
        data = response.json()
        uid = data.get("uid") if isinstance(data, dict) else ""
        if not isinstance(uid, str) or not uid:
            raise RuntimeError("微信读书没有返回有效的扫码登录 UID")
        session_id = uuid.uuid4().hex
        confirm_url = f"{WEREAD_BASE}/web/confirm?uid={quote(uid, safe='')}"
        session = {
            "created_at": time.time(), "client": client, "uid": uid,
            "confirm_url": confirm_url, "qr_svg": _qr_svg(confirm_url),
        }
        _QR_SESSIONS[session_id] = session
        return {"session_id": session_id, "confirm_url": confirm_url}
    except Exception:
        await client.aclose()
        raise


def _qr_session(session_id: str) -> Dict:
    _cleanup_qr_sessions()
    session = _QR_SESSIONS.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="二维码已过期，请重新生成")
    return session


async def _finish_qr_login(session: Dict, result: Dict) -> Dict:
    vid = str(result.get("webLoginVid") or "").strip()
    access_token = str(result.get("accessToken") or "").strip()
    refresh_token = str(result.get("refreshToken") or "").strip()
    if not vid or not access_token:
        raise RuntimeError("扫码成功，但微信读书未返回完整登录凭证")
    cookies = {"wr_vid": vid, "wr_skey": access_token, "wr_ql": "0"}
    if refresh_token:
        cookies["wr_rt"] = quote(refresh_token, safe="")
    # 保留 getLoginUid/getLoginInfo 期间下发的会话 Cookie；参考实现也是在
    # 同一个 Session 中安装登录凭证后继续验证和 renewal。
    login_client = session["client"]
    for key, value in cookies.items():
        login_client.cookies.set(key, value, domain=".weread.qq.com", path="/")
    # 扫码协议只稳定返回普通 Web Cookie，不会凭空生成公众号文章列表所需的
    # x-wr-ticket/x-wrpa-0。若本机已有同一账号的票据，沿用它并交给 renewal
    # 刷新；首次配置仍需从浏览器 /web/mp/articles cURL 导入票据。
    existing = auth_manager.get_credentials() or {}
    same_account = bool(existing.get("vid") and str(existing.get("vid")) == vid)
    wpa = {
        "ticket": str(existing.get("ticket") or "").strip() if same_account else "",
        "wrpa": str(existing.get("wrpa") or "").strip() if same_account else "",
    }
    diagnostics = []

    def collect_wpa(stage: str, response) -> None:
        response_ticket = response.headers.get("x-wr-ticket", "").strip()
        response_wrpa = response.headers.get("x-wrpa-0", "").strip()
        if response_ticket:
            wpa["ticket"] = response_ticket
        if response_wrpa:
            wpa["wrpa"] = response_wrpa
        try:
            body = response.json()
            body_keys = sorted(body.keys()) if isinstance(body, dict) else []
            error_code = body.get("errCode", body.get("errcode")) if isinstance(body, dict) else None
        except Exception:
            body_keys, error_code = [], None
        item = {
            "stage": stage,
            "status": response.status_code,
            "body_keys": body_keys[:30],
            "error_code": error_code,
            "has_set_cookie": bool(response.headers.get("set-cookie")),
            "has_x_wr_ticket": bool(response.headers.get("x-wr-ticket")),
            "has_x_wrpa_0": bool(response.headers.get("x-wrpa-0")),
            "cookie_names": sorted({cookie.name for cookie in login_client.cookies.jar}),
        }
        diagnostics.append(item)
        logger.info("[QR-WPA-DIAG] %s", json.dumps(item, ensure_ascii=False, sort_keys=True))

    # renewal 沿用扫码轮询的原始 Cookie 会话；若有同账号的旧文章列表票据，
    # 同时带上以便服务端续期。
    renewal_headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": WEREAD_BASE,
        "Referer": f"{WEREAD_BASE}/",
    }
    if wpa["ticket"]:
        renewal_headers["x-wr-ticket"] = wpa["ticket"]
    if wpa["wrpa"]:
        renewal_headers["x-wrpa-0"] = wpa["wrpa"]
    renewal_client = login_client
    renewal_errors = []
    renewal_response = None
    for payload in (
        {"rq": "%2Fweb%2Fbook%2Fread", "ql": False},
        {"rq": "%2Fweb%2Fbook%2Fread", "ql": True},
        {"rq": "%2Fweb%2Fbook%2Fread"},
    ):
        try:
            response = await renewal_client.post(
                f"{WEREAD_BASE}/web/login/renewal",
                content=json.dumps(payload, separators=(",", ":")),
                headers=renewal_headers,
                # 让 httpx 按 Cookie 规则编码 token，避免手工 Cookie 头破坏
                # 含特殊字符的 wr_skey/wr_rt；形态与参考实现一致。
                cookies=cookies,
            )
            collect_wpa("renewal", response)
            response.raise_for_status()
            data = response.json()
            if _web_json_succeeded(response) and data.get("succ") in (1, True, "1", None):
                renewal_response = response
                break
            renewal_errors.append(str(data.get("errMsg") or data.get("errmsg") or data.get("errCode") or "续期失败"))
        except Exception as exc:
            renewal_errors.append(str(exc))
    if renewal_response is None:
        raise RuntimeError("扫码成功，但 renewal 鉴权失败: " + "；".join(dict.fromkeys(renewal_errors[-3:])))

    # httpx 已把 Set-Cookie 合并到原始 Cookie Jar；优先采用任一 Web 响应头中的 WPA。
    renewed_cookie = _cookie_header(renewal_client)
    candidate = {
        "cookie": renewed_cookie, "ticket": wpa["ticket"], "wrpa": wpa["wrpa"], "vid": vid,
    }
    if not (candidate["ticket"] or candidate["wrpa"]):
        diag_code = "QR_WPA_DIAG_" + uuid.uuid4().hex[:12].upper()
        logger.warning(
            "[%s] 扫码成功但未发现 WPA；脱敏诊断=%s",
            diag_code,
            json.dumps(diagnostics, ensure_ascii=False, sort_keys=True),
        )
        raise RuntimeError(
            "扫码已取得普通 Cookie，但尚未完成公众号文章列表登录：当前没有可验证的"
            " x-wr-ticket/x-wrpa-0。请停止重复扫码，必须先使用“完整 cURL 导入”成功登录一次："
            "①在浏览器登录同一微信读书账号并打开书架中的公众号文章列表；"
            "②在开发者工具 Network 中找到响应成功的 /web/mp/articles 请求，确认请求头包含"
            " x-wr-ticket 或 x-wrpa-0，再选择 Copy as cURL；"
            "③回到本机登录页，粘贴完整 cURL 并点击“校验并保存”，直到页面显示"
            "“微信读书凭证有效，发现 N 个公众号”。成功一次后，后续扫码才可尝试刷新同账号"
            " Cookie 和续期文章列表票据。完整 cURL、Cookie 和 token 只能输入本机登录页，"
            f"不要提供给他人；诊断码：{diag_code}"
        )
    client = WereadClient(candidate)
    check = await client.check_auth()
    credentials = client.credentials
    if not auth_manager.save_credentials(
        cookie=credentials.get("cookie", ""), ticket=credentials.get("ticket", ""),
        wrpa=credentials.get("wrpa", ""), vid=credentials.get("vid", ""),
    ):
        raise RuntimeError("凭证有效，但本地保存失败")
    await webhook.notify("login_success", {"nickname": "微信读书"})
    return check


class LoginRequest(BaseModel):
    cookie: str = Field("", description="weread.qq.com 完整 Cookie")
    ticket: str = Field("", description="可选：/web/mp/articles 请求头中的 x-wr-ticket")
    wrpa: str = Field("", description="可选：x-wrpa-0")
    vid: Optional[str] = Field("", description="可选；默认从 wr_vid Cookie 提取")
    curl: str = Field("", description="可选：浏览器 Copy as cURL 的完整请求，仅本机处理")


@router.post("/qr/start", summary="创建微信读书扫码登录会话")
async def qr_start():
    try:
        return {"success": True, "data": await _new_qr_session()}
    except Exception as exc:
        return {"success": False, "message": f"无法创建扫码登录: {exc}"}


@router.get("/qr/image", summary="获取扫码登录二维码", include_in_schema=False)
async def qr_image(session_id: str = Query(..., min_length=20, max_length=64)):
    session = _qr_session(session_id)
    return Response(content=session["qr_svg"], media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@router.post("/qr/poll", summary="轮询微信读书扫码登录状态")
async def qr_poll(session_id: str = Query(..., min_length=20, max_length=64), otp: str = ""):
    session = _qr_session(session_id)
    client = session["client"]
    try:
        suffix = "&otp=" + quote(otp, safe="") if otp else "&otp"
        response = await client.get(
            f"{WEREAD_BASE}/api/auth/getLoginInfo?uid={quote(session['uid'], safe='')}{suffix}",
            headers={"Referer": f"{WEREAD_BASE}/r/weread-skills"},
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict):
            raise RuntimeError("扫码状态响应格式异常")
        if result.get("succeed") is not True:
            logic_code = str(result.get("logicCode") or "WAITING")
            if logic_code == "NEED_OTP":
                return {"success": True, "status": "need_otp", "message": "请填写微信中显示的四位验证码"}
            if logic_code in {"LOGIN_TIMEOUT", "OTP_EXPIRED"}:
                session["finished"] = True
                return {"success": False, "status": "expired", "message": "二维码已过期，请重新生成"}
            return {"success": True, "status": "waiting", "message": "等待微信确认扫码"}
        check = await _finish_qr_login(session, result)
        session["finished"] = True
        return {"success": True, "status": "success", "message": f"扫码登录成功，发现 {check.get('account_count', 0)} 个公众号", "data": check}
    except Exception as exc:
        return {"success": False, "status": "error", "message": f"扫码登录失败: {exc}"}
    finally:
        if session_id in _QR_SESSIONS and session.get("finished"):
            await client.aclose()
            _QR_SESSIONS.pop(session_id, None)


@router.post("/manual", summary="保存并校验微信读书凭证")
async def manual_login(request: LoginRequest):
    try:
        imported = parse_curl_credentials(request.curl)
    except Exception as exc:
        return {"success": False, "message": f"凭证校验失败，未保存: {exc}"}
    cookie = imported["cookie"] or request.cookie.strip()
    ticket = imported["ticket"] or request.ticket.strip()
    wrpa = imported["wrpa"] or request.wrpa.strip()
    vid = imported["vid"] or (request.vid or "").strip()
    if len(cookie) < 8:
        return {"success": False, "message": "凭证校验失败，未保存: 请填写 Cookie，或粘贴包含 Cookie 请求头的完整 cURL"}
    candidate = {
        "cookie": cookie,
        "ticket": ticket,
        "wrpa": wrpa,
        "vid": vid,
    }
    try:
        client = WereadClient(candidate)
        renewal_error = ""
        try:
            await client.renew_mp_auth()
        except Exception as exc:
            renewal_error = str(exc)
            if not (ticket or wrpa):
                raise
        check = await client.check_auth()
    except Exception as exc:
        return {"success": False, "message": f"凭证校验失败，未保存: {exc}"}
    credentials = client.credentials
    if not auth_manager.save_credentials(
        cookie=credentials.get("cookie", ""),
        ticket=credentials.get("ticket", ""),
        wrpa=credentials.get("wrpa", ""),
        vid=credentials.get("vid", ""),
    ):
        return {"success": False, "message": "凭证有效，但本地保存失败"}
    await webhook.notify("login_success", {"nickname": "微信读书"})
    return {
        "success": True,
        "message": f"微信读书凭证有效，发现 {check.get('account_count', 0)} 个公众号",
        "data": {**check, "renewed": not bool(renewal_error)},
    }


@router.get("/check", summary="在线校验微信读书凭证")
async def check_login():
    try:
        data = await WereadClient().check_auth()
        return {"success": True, "data": data, "message": "微信读书登录有效"}
    except WereadError as exc:
        return {"success": False, "error": str(exc)}


@router.get("/info", summary="获取微信读书凭证配置状态")
async def get_login_info():
    status = auth_manager.get_status()
    return {
        "success": bool(status.get("authenticated")),
        "data": {
            "nickname": "微信读书",
            "vid": status.get("fakeid", ""),
            "auth_type": "weread-cookie-wpa",
            "expire_time": 0,
        },
        "error": None if status.get("authenticated") else "未配置微信读书凭证",
    }


@router.post("/logout", summary="清除微信读书凭证")
async def logout():
    success = auth_manager.clear_credentials()
    return {"success": success, "message": "凭证已清除" if success else "清除失败"}
