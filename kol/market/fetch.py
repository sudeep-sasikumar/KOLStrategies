"""Daily fetch from DefiLlama (sources A-F). One failing request never stops the run.

Rules:
- Only completed UTC days are stored in mc_daily_metrics; the current day is partial and skipped.
- Every run upserts the last `revise_days` days (DefiLlama revises recent days); a backfill stores everything.
- Price for day D = the price at D+1 00:00 UTC (the day's close). DefiLlama's daily points sit at midnight.
- Every response, good or bad, is kept in mc_raw_snapshots.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

import aiohttp

from . import store

log = logging.getLogger("kol.market.fetch")


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _day(ts) -> date:
    return datetime.fromtimestamp(int(float(ts)), timezone.utc).date()


async def _get(session: aiohttp.ClientSession, url: str, f: dict) -> tuple[int | None, str | None, str | None]:
    """(status, body, error) after up to `retries` retries with exponential backoff."""
    last_err, status = None, None
    for attempt in range(f["retries"] + 1):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=f["timeout_s"])) as r:
                status = r.status
                body = await r.text()
                if r.status == 200:
                    return status, body, None
                last_err = f"HTTP {r.status}: {body[:200]}"
                if r.status in (400, 401, 402, 403, 404):
                    break                          # will not get better with a retry
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            last_err = f"{type(e).__name__}: {e}"[:300]
        if attempt < f["retries"]:
            await asyncio.sleep(f["backoff_s"] * 2 ** attempt)
    return status, None, last_err


# ---- parsers: response JSON -> metric rows (date, metric, entity, value, source) -------------------
def parse_volume_chart(j: dict, metric: str, entity: str, source: str) -> list[tuple]:
    return [(_day(ts), metric, entity, float(v), source) for ts, v in j.get("totalDataChart") or [] if v is not None]


def parse_stablecoins(j: list, entity: str) -> list[tuple]:
    out = []
    for p in j or []:
        v = ((p.get("totalCirculatingUSD") or {}).get("peggedUSD"))
        if v is not None:
            out.append((_day(p["date"]), "stablecoin_supply_usd", entity, float(v), "D"))
    return out


def parse_price_chart(j: dict, coin_id: str, entity: str) -> list[tuple]:
    out = []
    for p in ((j.get("coins") or {}).get(coin_id) or {}).get("prices") or []:
        midnight = date.fromordinal(date(1970, 1, 1).toordinal() + round(p["timestamp"] / 86400))
        out.append((midnight - timedelta(days=1), "price_usd", entity, float(p["price"]), "F"))
    return out


def keep(rows: list[tuple], today: date, since: date | None) -> list[tuple]:
    """Completed days only (before today, UTC); from `since` on unless backfilling."""
    return [(d.isoformat(), m, e, v, s) for d, m, e, v, s in rows if d < today and (since is None or d >= since)]


async def run(conn, session: aiohttp.ClientSession, cfg: dict, backfill: bool = False) -> dict:
    """Fetch every enabled source; store what works. Returns {ok, failed, rows}."""
    f = cfg["fetch"]
    started = time.time()
    today = utc_today()
    since = None if backfill else today - timedelta(days=f["revise_days"])
    src = cfg["sources"]
    jobs: list[tuple[str, str, str, callable]] = []   # (source, key, url, parser)

    def add(code: str, key: str, url: str, parser):
        if src[code].get("enabled", True):
            jobs.append((code, key, url, parser))

    for chain in cfg["dex_chains"]:
        add("A", chain, src["A"]["url"].format(key=quote(chain)),
            lambda j, c=chain: parse_volume_chart(j, "dex_volume_usd", c, "A"))
    for code, entity in (("B", "pump.fun"), ("C", "pumpswap")):
        slug = cfg["launchpads"][entity]
        add(code, entity, src[code]["url"].format(key=quote(slug)),
            lambda j, e=entity, c=code: parse_volume_chart(j, "launchpad_volume_usd", e, c))
    for chain in cfg["stablecoin_chains"]:
        add("D", chain, src["D"]["url"].format(key=quote(chain)), lambda j, c=chain: parse_stablecoins(j, c))
    add("E", ",".join(cfg["prices"].values()), src["E"]["url"].format(key=",".join(cfg["prices"].values())),
        lambda j: [])                              # kept as a raw snapshot only (today is partial)
    days = f["price_backfill_days"] if backfill else f["revise_days"] + 1
    days = min(days, f["price_max_points_per_request"] - 1)   # DefiLlama: max 500 points per request
    start = int(datetime(today.year, today.month, today.day, tzinfo=timezone.utc).timestamp()) - days * 86400
    for entity, coin in cfg["prices"].items():    # one coin per request: points = coins x span
        add("F", entity, src["F"]["url"].format(key=coin, start=start, span=days + 1),
            lambda j, c=coin, e=entity: parse_price_chart(j, c, e))

    ok, failed, rows_total = [], [], 0
    for code, key, url, parser in jobs:
        status, body, err = await _get(session, url, f)
        rows: list[tuple] = []
        if body is not None:
            try:
                rows = keep(parser(json.loads(body)), today, since)
            except (ValueError, KeyError, TypeError) as e:
                err = f"parse error: {e}"[:300]
        label = f"{src[code]['name']} ({key})" if code != "E" else src[code]["name"]

        def write(code=code, key=key, status=status, body=body, err=err, rows=rows):
            # runs in a worker thread: it may wait for the collector's transaction without blocking the loop
            store.save_raw(conn, code, key, status, body if err is None else (body or "")[:2000] or None, err)
            n = 0 if err else store.upsert_metrics(conn, rows)
            conn.commit()
            return n
        rows_total += await asyncio.to_thread(write)
        if err:
            failed.append(label)
            log.warning("market fetch %s %s failed: %s", code, key, err)
        else:
            ok.append(label)
        await asyncio.sleep(f["pause_s"])

    note = "backfill" if backfill else f"last {f['revise_days']} days"
    disabled = [f"{s['name']}: {s.get('note', 'disabled')}" for s in src.values() if not s.get("enabled", True)]
    def log_run():
        conn.execute("INSERT INTO mc_fetch_log (started_at_utc, finished_at_utc, kind, ok_sources, failed_sources, "
                     "rows_upserted, note) VALUES (?,?,?,?,?,?,?)",
                     (started, time.time(), "backfill" if backfill else "daily", json.dumps(ok), json.dumps(failed),
                      rows_total, "; ".join([note] + disabled)))
        conn.commit()
    await asyncio.to_thread(log_run)
    return {"ok": ok, "failed": failed, "rows": rows_total}
