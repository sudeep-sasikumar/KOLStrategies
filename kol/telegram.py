"""Telegram (Bot API). For now only a start-up notice: strategy signals are off until asked for.

Send-only (no getUpdates polling), so the same bot can be shared with the other apps on the VPS.
Without TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID messages only go to the log.
"""
from __future__ import annotations

import asyncio
import html
import logging

import aiohttp

log = logging.getLogger("kol.telegram")

SIGNALS_ENABLED = False      # data collection only; flip when the strategy signals are designed


def esc(text) -> str:
    return html.escape(str(text), quote=False)


class Telegram:
    def __init__(self, session: aiohttp.ClientSession, token: str, chat_id: str):
        self.session, self.token, self.chat_id = session, token, chat_id
        self.enabled = bool(token and chat_id)

    async def send(self, text: str) -> bool:
        if not self.enabled:
            log.info("[telegram not configured]\n%s", text)
            return False
        for attempt in range(3):
            try:
                async with self.session.post(
                        f"https://api.telegram.org/bot{self.token}/sendMessage",
                        json={"chat_id": self.chat_id, "text": text[:4000], "parse_mode": "HTML",
                              "disable_web_page_preview": True},
                        timeout=aiohttp.ClientTimeout(total=20)) as r:
                    j = await r.json(content_type=None)
                if j.get("ok"):
                    return True
                log.warning("telegram rejected message: %s", str(j)[:200])
                if j.get("error_code") != 429:
                    return False
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                log.warning("telegram send failed: %s", e)
            await asyncio.sleep(2 ** attempt * 2)
        return False
