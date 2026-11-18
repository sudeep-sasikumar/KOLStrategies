"""Start the collector and the dashboard:  python -m kol"""
from __future__ import annotations

import asyncio
import logging
import sys

import aiohttp

from . import config, db
from .collector import Collector
from .strategies import STRATEGIES
from .telegram import Telegram, esc
from .web import serve


async def main() -> None:
    s = config.load()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    log = logging.getLogger("kol")
    log.info("environment: %s", ", ".join(
        f"{k} {'set' if v else 'MISSING'}" for k, v in (("TELEGRAM_BOT_TOKEN", s.tg_token),
                                                         ("TELEGRAM_CHAT_ID", s.tg_chat),
                                                         ("DASHBOARD_PASSWORD", s.password))))
    log.info("solana rpc: %s", "public mainnet RPC" if s.public_rpc else "custom (SOLANA_RPC_URL)")
    conn = db.connect(s.db_path)
    db.init(conn)
    headers = {"User-Agent": "kol-strategies/1.0"}
    async with aiohttp.ClientSession(headers=headers) as session:
        coll = Collector(s, conn, session)
        await serve(coll, s)
        tg = Telegram(session, s.tg_token, s.tg_chat)
        link = f"\nDashboard: https://{s.domain}{s.base_path}/" if s.domain else ""
        asyncio.create_task(tg.send(
            f"🟢 <b>KOL Strategies</b> collector online ({esc(s.version)})\n"
            f"Strategies: {esc(', '.join(x.name for x in STRATEGIES))}\n"
            f"Collecting data only - no signals.{link}"))
        try:
            await coll.run()
        finally:
            coll.flush()
            conn.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
