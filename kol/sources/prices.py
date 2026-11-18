"""SOL/USD price (Binance, Coinbase as fallback), refreshed every minute."""
from __future__ import annotations

import asyncio
import logging

import aiohttp

log = logging.getLogger("kol.prices")


async def fetch_sol_usd(session: aiohttp.ClientSession) -> float | None:
    sources = (
        ("https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT", lambda j: j["price"]),
        ("https://api.coinbase.com/v2/prices/SOL-USD/spot", lambda j: j["data"]["amount"]),
        ("https://api.kraken.com/0/public/Ticker?pair=SOLUSD", lambda j: next(iter(j["result"].values()))["c"][0]),
    )
    for url, pick in sources:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    p = float(pick(await r.json(content_type=None)))
                    if p > 0:
                        return p
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, StopIteration, TypeError):
            continue
    return None
