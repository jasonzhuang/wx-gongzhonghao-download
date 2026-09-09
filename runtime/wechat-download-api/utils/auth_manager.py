#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微信读书 Web 凭证管理。

公众号后台的 appmsgpublish 已不可用，服务改用微信读书 Web 的公众号书架、
文章列表和正文接口。凭证只写入 data/.weread_credentials.json；环境变量仅作
无状态部署的只读回退，避免 Docker 只读 .env 与运行时凭证不一致。
"""

import json
import os
import time
from pathlib import Path
from typing import Dict, Optional


class AuthManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.base_dir = Path(__file__).parent.parent
        self.credentials_file = self.base_dir / "data" / ".weread_credentials.json"
        self._last_loaded_at = 0.0
        self._load_ttl = 30.0
        self.credentials: Dict = {}
        self._load_credentials(force=True)
        self._initialized = True

    @staticmethod
    def _vid_from_cookie(cookie: str) -> str:
        for part in (cookie or "").split(";"):
            key, sep, value = part.strip().partition("=")
            if sep and key == "wr_vid":
                return value.strip()
        return ""

    def _load_credentials(self, force: bool = False):
        now = time.time()
        if not force and now - self._last_loaded_at < self._load_ttl:
            return
        self._last_loaded_at = now

        data = {}
        if self.credentials_file.exists():
            try:
                data = json.loads(self.credentials_file.read_text(encoding="utf-8"))
            except Exception as exc:
                print(f"[WARN] 无法读取微信读书凭证: {exc}")

        if not data:
            cookie = os.getenv("WEREAD_COOKIE", "").strip()
            data = {
                "cookie": cookie,
                "ticket": os.getenv("WEREAD_TICKET", "").strip(),
                "wrpa": os.getenv("WEREAD_WRPA", "").strip(),
                "vid": os.getenv("WEREAD_VID", "").strip() or self._vid_from_cookie(cookie),
                "nickname": "微信读书",
                "configured_at": 0,
            }
        self.credentials = data

    def save_credentials(self, cookie: str, ticket: str = "", wrpa: str = "", vid: str = "",
                         nickname: str = "微信读书", cookie_only: bool = False) -> bool:
        cookie = (cookie or "").strip()
        ticket = (ticket or "").strip()
        wrpa = (wrpa or "").strip()
        vid = (vid or "").strip() or self._vid_from_cookie(cookie)
        if not cookie or not (ticket or wrpa or cookie_only):
            return False

        self.credentials = {
            "cookie": cookie,
            "ticket": ticket,
            "wrpa": wrpa,
            "vid": vid,
            "cookie_only": bool(cookie_only and not (ticket or wrpa)),
            "nickname": nickname or "微信读书",
            "configured_at": int(time.time()),
        }
        try:
            self.credentials_file.parent.mkdir(parents=True, exist_ok=True)
            self.credentials_file.write_text(
                json.dumps(self.credentials, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            try:
                self.credentials_file.chmod(0o600)
            except OSError:
                pass
            self._last_loaded_at = time.time()
            return True
        except Exception as exc:
            print(f"[ERROR] 保存微信读书凭证失败: {exc}")
            return False

    def get_credentials(self) -> Optional[Dict]:
        self._load_credentials()
        if not self.credentials.get("cookie") or not (
            self.credentials.get("ticket")
            or self.credentials.get("wrpa")
            or self.credentials.get("cookie_only")
        ):
            return None
        return dict(self.credentials)

    def get_cookie(self) -> Optional[str]:
        creds = self.get_credentials()
        return creds.get("cookie") if creds else None

    def get_status(self) -> Dict:
        creds = self.get_credentials()
        configured = bool(creds)
        vid = (creds or {}).get("vid", "")
        return {
            "authenticated": configured,
            "loggedIn": configured,
            "account": vid or "微信读书",
            "nickname": "微信读书",
            "fakeid": vid,
            "expireTime": 0,
            "isExpired": False,
            "status": "微信读书凭证已配置，需在线校验" if configured else "未配置微信读书 Cookie/文章列表凭证",
        }

    def clear_credentials(self) -> bool:
        self.credentials = {}
        self._last_loaded_at = time.time()
        try:
            if self.credentials_file.exists():
                self.credentials_file.unlink()
            return True
        except Exception as exc:
            print(f"[ERROR] 清除微信读书凭证失败: {exc}")
            return False


auth_manager = AuthManager()
