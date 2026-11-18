"""Token metadata JSON (IPFS): the socials the creator linked (twitter, telegram, website)."""
from __future__ import annotations

import asyncio

import aiohttp

GATEWAYS = ("https://ipfs.io/ipfs/", "https://dweb.link/ipfs/")


def _candidates(uri: str) -> list[str]:
    if "/ipfs/" in uri:
        cid = uri.split("/ipfs/", 1)[1]
        return [uri] + [g + cid for g in GATEWAYS if not uri.startswith(g)]
    return [uri]


async def fetch_socials(session: aiohttp.ClientSession, uri: str) -> dict | None:
    if not uri.startswith("http"):
        return None
    for url in _candidates(uri):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    continue
                j = await r.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            continue
        if not isinstance(j, dict):
            return None
        ext = j.get("extensions") if isinstance(j.get("extensions"), dict) else {}
        pick = lambda k: str(j.get(k) or ext.get(k) or "")[:200]  # noqa: E731
        return {"twitter": pick("twitter"), "telegram": pick("telegram"), "website": pick("website")}
    return None
