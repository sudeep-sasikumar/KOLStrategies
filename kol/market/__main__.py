"""Manual commands for the Market Conditions module.

  python -m kol.market backfill                       fetch all available history
  python -m kol.market fetch                          normal daily fetch (last 14 days)
  python -m kol.market report daily|weekly|monthly    build the latest completed period's report
        [--start YYYY-MM-DD] [--send]                 any period (its first day); --send posts it to Telegram
  python -m kol.market check                          backfill check against reference values
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date

import aiohttp

from .. import config, db
from ..telegram import Telegram
from . import calc, fetch, reports, scheduler, settings, store


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m kol.market")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("backfill")
    sub.add_parser("fetch")
    r = sub.add_parser("report")
    r.add_argument("kind", choices=scheduler.KINDS)
    r.add_argument("--start", type=date.fromisoformat)
    r.add_argument("--send", action="store_true")
    sub.add_parser("check")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    s = config.load()
    cfg = settings.load()
    conn = db.connect(s.db_path)
    store.init(conn)
    async with aiohttp.ClientSession(headers={"User-Agent": "kol-strategies/1.0"}) as session:
        if a.cmd in ("backfill", "fetch"):
            res = await fetch.run(conn, session, cfg, backfill=a.cmd == "backfill")
            print(f"rows upserted: {res['rows']}\nok: {len(res['ok'])}\nfailed: {res['failed'] or 'none'}")
        elif a.cmd == "report":
            start = calc.period_of(a.kind, a.start)[0] if a.start else calc.last_completed(a.kind, fetch.utc_today())
            rep = reports.generate(conn, cfg, a.kind, start)
            print(rep["text"])
            if a.send:
                tg = Telegram(session, s.tg_token, s.tg_chat)
                if not tg.enabled:
                    print("\nTelegram is not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID).")
                    return 1
                ok = await scheduler.send_report(conn, tg, rep["id"])
                print("\nsent to Telegram" if ok else "\nTelegram send FAILED")
        elif a.cmd == "check":
            print(check(conn))
    return 0


REFERENCE = (  # read from the same endpoints on 18 Nov 2026 (task brief)
    ("weekly", "2026-11-09", "launchpad_volume_usd", "pump.fun", 674e6),
    ("weekly", "2026-11-09", "launchpad_volume_usd", "pumpswap", 1513e6),
    ("weekly", "2026-11-09", "dex_volume_usd", "Solana", 10554e6),
    ("weekly", "2026-10-05", "launchpad_volume_usd", "pump.fun", 1186e6),
    ("weekly", "2026-09-14", "dex_volume_usd", "Solana", 20022e6),
)


def check(conn) -> str:
    out = []
    for kind, start, metric, entity, ref in REFERENCE:
        v = calc.value(store.series(conn, metric, entity), metric, kind, date.fromisoformat(start))
        diff = calc.pct(v, ref)
        status = "OK" if diff is not None and abs(diff) <= 3 else "CHECK"
        out.append(f"{status:5} week {start} {entity:9} {metric:22} stored {v / 1e6 if v else float('nan'):>9,.0f}M "
                   f"ref {ref / 1e6:>7,.0f}M diff {diff if diff is not None else float('nan'):+.2f}%")
    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
