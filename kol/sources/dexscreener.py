"""DexScreener: market cap, volume, buys/sells and pairs for up to 30 tokens per request (free).

Limit published by DexScreener for /tokens/v1: 300 requests per minute. We stay at 200.
"""
from __future__ import annotations

import asyncio
import logging

import aiohttp

from .ratelimit import RateLimiter

log = logging.getLogger("kol.dexscreener")
URL = "https://api.dexscreener.com/tokens/v1/solana/"
BATCH = 30


class DexScreener:
    def __init__(self, session: aiohttp.ClientSession, per_min: int = 200):
        self.session = session
        self.limiter = RateLimiter(per_min / 60)
        self.requests = 0
        self.errors = 0
        self.last_error = ""

    async def tokens(self, mints: list[str]) -> dict[str, list[dict]] | None:
        """{mint: [pairs]} for the mints DexScreener knows. None when the request failed."""
        await self.limiter.wait()
        self.requests += 1
        try:
            async with self.session.get(URL + ",".join(mints), timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status == 429:
                    self.limiter.penalize(30)
                    self.errors += 1
                    self.last_error = "429 rate limited"
                    return None
                if r.status != 200:
                    self.errors += 1
                    self.last_error = f"HTTP {r.status}"
                    return None
                data = await r.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            self.errors += 1
            self.last_error = str(e)[:120] or type(e).__name__
            return None
        out: dict[str, list[dict]] = {}
        for p in data or []:
            base = (p.get("baseToken") or {}).get("address")
            if base:
                out.setdefault(base, []).append(p)
        return out


def summarize(pairs: list[dict]) -> dict:
    """One view of a token across its pairs (bonding curve and/or AMM)."""
    main = max(pairs, key=lambda p: ((p.get("liquidity") or {}).get("usd") or 0, p.get("marketCap") or 0))
    vol_bc = sum((p.get("volume") or {}).get("h24") or 0 for p in pairs if p.get("dexId") == "pumpfun")
    vol_amm = sum((p.get("volume") or {}).get("h24") or 0 for p in pairs if p.get("dexId") != "pumpfun")
    buys = sum(((p.get("txns") or {}).get("h24") or {}).get("buys") or 0 for p in pairs)
    sells = sum(((p.get("txns") or {}).get("h24") or {}).get("sells") or 0 for p in pairs)
    amm_txns = sum(sum((((p.get("txns") or {}).get("h24") or {}).get(k) or 0) for k in ("buys", "sells"))
                   for p in pairs if p.get("dexId") != "pumpfun")
    info = main.get("info") or {}
    socials = {s.get("type"): s.get("url") for s in info.get("socials") or [] if s.get("type")}
    sites = [w.get("url") for w in info.get("websites") or [] if w.get("url")]
    return {
        "mc": main.get("marketCap") or main.get("fdv"),
        "liq": (main.get("liquidity") or {}).get("usd"),
        "pair": main.get("pairAddress") or "",
        "name": str((main.get("baseToken") or {}).get("name") or "")[:80],
        "symbol": str((main.get("baseToken") or {}).get("symbol") or "")[:30],
        "dex_id": main.get("dexId") or "",
        "has_bc": any(p.get("dexId") == "pumpfun" for p in pairs),
        "has_amm": any(p.get("dexId") != "pumpfun" for p in pairs),
        "vol_bc": vol_bc, "vol_amm": vol_amm, "amm_txns": amm_txns,
        "buys": buys, "sells": sells,
        "price_native": float(main.get("priceNative") or 0) or None,
        "twitter": socials.get("twitter") or "", "telegram": socials.get("telegram") or "",
        "website": sites[0] if sites else "",
    }
