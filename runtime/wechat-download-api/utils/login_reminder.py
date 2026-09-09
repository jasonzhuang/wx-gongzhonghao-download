#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""定期在线校验微信读书 Cookie/Ticket，并在失效时通知。"""

import asyncio
import logging
from typing import Optional

from utils.auth_manager import auth_manager
from utils.webhook import webhook
from utils.weread_client import WereadClient

logger = logging.getLogger(__name__)


class LoginReminder:
    def __init__(self):
        self.check_interval = 6 * 3600
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._notified = False

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self):
        while self._running:
            try:
                await self._check_login_status()
            except Exception as exc:
                logger.warning("微信读书登录校验失败: %s", exc)
            await asyncio.sleep(self.check_interval)

    async def _check_login_status(self):
        if not auth_manager.get_credentials():
            return
        try:
            await WereadClient().check_auth()
            self._notified = False
        except Exception as exc:
            if not self._notified:
                await webhook.notify("login_expired", {
                    "nickname": "微信读书",
                    "message": f"微信读书 Cookie/Ticket 已失效，请重新配置: {exc}",
                })
                self._notified = True


login_reminder = LoginReminder()
