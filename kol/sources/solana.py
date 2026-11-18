"""Solana RPC: holders, dev and sniper holdings, transaction count and a fee estimate.

All on-demand, only for tokens a strategy column is interested in. Works on the public RPC
(about 4 requests/s per method); a private RPC in SOLANA_RPC_URL makes it faster.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import struct
from collections import defaultdict

import aiohttp

from ..util import b58encode
from .ratelimit import RateLimiter

log = logging.getLogger("kol.solana")

TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
SPL_TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
JITO_TIP_ACCOUNTS = {
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5", "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY", "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
    "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh", "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
    "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL", "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
}


class RPCError(Exception):
    pass


class SolanaRPC:
    def __init__(self, session: aiohttp.ClientSession, url: str, rps: float, public: bool):
        self.session, self.url = session, url
        self.limiter = RateLimiter(rps)
        per_method = min(rps, 2.5) if public else rps
        self.method_limiters: dict[str, RateLimiter] = defaultdict(lambda: RateLimiter(per_method))
        self.calls = 0
        self.errors = 0
        self.last_error = ""

    async def call(self, method: str, params: list):
        for attempt in range(5):
            await self.limiter.wait()
            await self.method_limiters[method].wait()
            self.calls += 1
            try:
                async with self.session.post(self.url, json={"jsonrpc": "2.0", "id": 1, "method": method,
                                                             "params": params},
                                             timeout=aiohttp.ClientTimeout(total=60)) as r:
                    if r.status == 429:
                        self._backoff(method, attempt, "429 rate limited")
                        await asyncio.sleep(2 ** attempt)
                        continue
                    if r.status >= 500:
                        self._backoff(method, attempt, f"HTTP {r.status}")
                        await asyncio.sleep(2 ** attempt)
                        continue
                    j = await r.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                self._backoff(method, attempt, str(e)[:100] or type(e).__name__)
                await asyncio.sleep(2 ** attempt)
                continue
            err = j.get("error")
            if err:
                if err.get("code") in (429, -32005, -32429):
                    self._backoff(method, attempt, f"{method}: rate limited")
                    await asyncio.sleep(2 ** attempt)
                    continue
                self.errors += 1
                self.last_error = f"{method}: {err.get('message', '')[:100]}"
                raise RPCError(self.last_error)
            return j.get("result")
        raise RPCError(f"{method}: gave up after retries ({self.last_error})")

    def _backoff(self, method: str, attempt: int, why: str) -> None:
        self.errors += 1
        self.last_error = why
        self.method_limiters[method].penalize(2 ** attempt)

    # ---- queries ------------------------------------------------------------------------------
    async def token_accounts(self, mint: str, program: str = "") -> tuple[str, list[tuple[str, int]]]:
        """(token program, [(owner, raw amount)]) for every account of this mint."""
        for prog in ([program] if program else [TOKEN_2022, SPL_TOKEN]):
            filters = [{"memcmp": {"offset": 0, "bytes": mint}}]
            if prog == SPL_TOKEN:
                filters.append({"dataSize": 165})
            res = await self.call("getProgramAccounts", [prog, {
                "encoding": "base64", "dataSlice": {"offset": 32, "length": 40}, "filters": filters}])
            if res:
                return prog, parse_token_accounts(res)
        return program, []

    async def supply(self, mint: str) -> float | None:
        res = await self.call("getTokenSupply", [mint])
        try:
            return float(res["value"]["amount"])
        except (TypeError, KeyError, ValueError):
            return None

    async def signatures(self, address: str, before: str | None = None, until: str | None = None,
                         limit: int = 1000) -> list[dict]:
        opts: dict = {"limit": limit}
        if before:
            opts["before"] = before
        if until:
            opts["until"] = until
        return await self.call("getSignaturesForAddress", [address, opts]) or []

    async def transaction(self, sig: str) -> dict | None:
        return await self.call("getTransaction", [sig, {"encoding": "jsonParsed",
                                                        "maxSupportedTransactionVersion": 1}])


# ---- parsing (pure functions, tested) ---------------------------------------------------------
def parse_token_accounts(res: list[dict]) -> list[tuple[str, int]]:
    out = []
    for a in res:
        try:
            raw = base64.b64decode(a["account"]["data"][0])
        except (KeyError, IndexError, ValueError):
            continue
        if len(raw) < 40:
            continue
        out.append((b58encode(raw[:32]), struct.unpack("<Q", raw[32:40])[0]))
    return out


def holdings(accounts: list[tuple[str, int]], supply: float, dev: str, snipers: set[str],
             exclude: set[str], insiders: set[str] | None = None) -> dict:
    """Holder count, dev %, sniper %, top-10 % (pool / bonding-curve accounts excluded)."""
    by_owner: dict[str, int] = defaultdict(int)
    for owner, amt in accounts:
        if amt > 0 and owner not in exclude:
            by_owner[owner] += amt
    supply = supply or 1.0
    top = sorted(by_owner.values(), reverse=True)[:10]
    return {
        "holders": len(by_owner),
        "dev_pct": by_owner.get(dev, 0) / supply * 100 if dev else None,
        "snipers_pct": sum(by_owner.get(s, 0) for s in snipers) / supply * 100,
        "insiders_pct": sum(by_owner.get(s, 0) for s in (insiders or ())) / supply * 100,
        "top10_pct": sum(top) / supply * 100,
    }


def _account_keys(tx: dict) -> list[str]:
    keys = ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
    return [k.get("pubkey") if isinstance(k, dict) else k for k in keys]


def tx_cost_sol(tx: dict) -> float:
    """Network fee (incl. priority fee) + Jito tips paid by the transaction, in SOL."""
    meta = tx.get("meta") or {}
    lamports = meta.get("fee") or 0
    ixs = list(((tx.get("transaction") or {}).get("message") or {}).get("instructions") or [])
    for inner in meta.get("innerInstructions") or []:
        ixs.extend(inner.get("instructions") or [])
    for ix in ixs:
        p = ix.get("parsed")
        if ix.get("program") == "system" and isinstance(p, dict) and p.get("type") == "transfer":
            info = p.get("info") or {}
            if info.get("destination") in JITO_TIP_ACCOUNTS:
                lamports += int(info.get("lamports") or 0)
    return lamports / 1e9


def token_deltas(tx: dict, mint: str) -> dict[str, int]:
    """Change of `mint` balance per owner in one transaction."""
    meta = tx.get("meta") or {}
    pre = {(b.get("accountIndex"), b.get("owner")): int((b.get("uiTokenAmount") or {}).get("amount") or 0)
           for b in meta.get("preTokenBalances") or [] if b.get("mint") == mint}
    post = {(b.get("accountIndex"), b.get("owner")): int((b.get("uiTokenAmount") or {}).get("amount") or 0)
            for b in meta.get("postTokenBalances") or [] if b.get("mint") == mint}
    out: dict[str, int] = defaultdict(int)
    for key in set(pre) | set(post):
        d = post.get(key, 0) - pre.get(key, 0)
        if d and key[1]:
            out[key[1]] += d
    return dict(out)


def signer(tx: dict) -> str:
    keys = _account_keys(tx)
    return keys[0] if keys else ""
