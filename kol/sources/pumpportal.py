"""PumpPortal websocket: every pump.fun token creation and every migration (both free).

Per-token trade streams need a funded PumpPortal API key, so they are not used; market data
comes from DexScreener and on-chain data from the Solana RPC instead.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable

import aiohttp

log = logging.getLogger("kol.pumpportal")

Handler = Callable[[dict], Awaitable[None]]


class PumpPortal:
    def __init__(self, session: aiohttp.ClientSession, url: str, on_create: Handler, on_migrate: Handler,
                 on_status: Callable[[bool, str], None]):
        self.session, self.url = session, url
        self.on_create, self.on_migrate, self.on_status = on_create, on_migrate, on_status
        self.connected = False
        self.messages = 0

    async def run(self) -> None:
        backoff = 2.0
        while True:
            try:
                async with self.session.ws_connect(self.url, heartbeat=30, max_msg_size=0) as ws:
                    await ws.send_str(json.dumps({"method": "subscribeNewToken"}))
                    await ws.send_str(json.dumps({"method": "subscribeMigration"}))
                    self.connected = True
                    self.on_status(True, "connected")
                    backoff = 2.0
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            if msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                                break
                            continue
                        self.messages += 1
                        try:
                            data = json.loads(msg.data)
                        except ValueError:
                            continue
                        tx = data.get("txType")
                        try:
                            if tx == "create" and data.get("mint"):
                                await self.on_create(data)
                            elif tx == "migrate" and data.get("mint"):
                                await self.on_migrate(data)
                        except Exception:  # noqa: BLE001 - one bad event must not drop the stream
                            log.exception("handler failed for %s", data.get("mint"))
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("pumpportal connection error: %s", e)
            if self.connected:
                self.connected = False
                self.on_status(False, "disconnected")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)
