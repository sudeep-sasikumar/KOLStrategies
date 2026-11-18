"""Runs inside the app's event loop: daily fetch at 01:30 UTC, reports at their Europe/London times.

- First start (no data yet): full backfill, then normal schedule.
- A report is sent once per period. If the app was down at send time, it is sent when it comes back,
  as long as that is within `send_window_h` hours of the scheduled time.
- Reports only ever cover completed UTC periods (never the current day).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

from .. import db
from . import calc, fetch, reports, settings, store

log = logging.getLogger("kol.market")
LONDON = ZoneInfo("Europe/London")
KINDS = ("daily", "weekly", "monthly")
MAX_SEND_ATTEMPTS = 5


def _hm(s: str) -> dtime:
    h, m = s.split(":")
    return dtime(int(h), int(m))


def scheduled_send(kind: str, cfg: dict, now_london: datetime) -> datetime | None:
    """Today's send time for this report kind (London), if today is a send day and the time has passed."""
    sc = cfg["schedule_london"][kind]
    if kind == "weekly" and now_london.weekday() != sc["weekday"]:
        return None
    if kind == "monthly" and now_london.day != sc["day"]:
        return None
    t = datetime.combine(now_london.date(), _hm(sc["time"]), LONDON)
    return t if now_london >= t else None


async def send_report(conn, tg, report_id: int) -> bool:
    row = conn.execute("SELECT summary_text FROM mc_reports WHERE id=?", (report_id,)).fetchone()
    if not row or tg is None:
        return False
    ok = await tg.send(reports.to_html(row[0]))
    if ok:
        def mark():
            conn.execute("UPDATE mc_reports SET telegram_sent=1 WHERE id=?", (report_id,))
            conn.commit()
        await asyncio.to_thread(mark)
    return ok


class MarketScheduler:
    def __init__(self, settings_, session, tg, cfg: dict | None = None):
        self.s, self.session, self.tg = settings_, session, tg
        self.cfg = cfg or settings.load()
        self.conn = db.connect(self.s.db_path)
        store.init(self.conn)
        self.running = False

    async def fetch(self, backfill: bool = False) -> dict:
        self.running = True
        try:
            res = await fetch.run(self.conn, self.session, self.cfg, backfill=backfill)
            log.info("market fetch (%s): %d rows, %d ok, failed: %s", "backfill" if backfill else "daily",
                     res["rows"], len(res["ok"]), res["failed"] or "none")
            return res
        finally:
            self.running = False

    async def tick(self, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        fetch_at = datetime.combine(now.date(), _hm(self.cfg["fetch"]["time_utc"]), timezone.utc)
        last = (await asyncio.to_thread(
            lambda: self.conn.execute("SELECT MAX(finished_at_utc) FROM mc_fetch_log").fetchone()[0])) or 0
        if now >= fetch_at and last < fetch_at.timestamp():
            await self.fetch()
        nl = now.astimezone(LONDON)
        window = timedelta(hours=self.cfg["send_window_h"])
        for kind in KINDS:
            due = scheduled_send(kind, self.cfg, nl)
            if due is None or nl - due > window:
                continue
            start = calc.last_completed(kind, now.date())
            key = f"attempts:{kind}:{start.isoformat()}"
            row = self.conn.execute("SELECT telegram_sent FROM mc_reports WHERE period_type=? AND period_start_utc=?",
                                    (kind, start.isoformat())).fetchone()
            attempts = store.get_state(self.conn, key, 0)
            if (row and row[0]) or attempts >= MAX_SEND_ATTEMPTS:
                continue
            def make(kind=kind, start=start, key=key, attempts=attempts):
                rep = reports.generate(self.conn, self.cfg, kind, start)
                no_tg = self.tg is None or not self.tg.enabled   # stored on the dashboard; nothing to send to
                store.set_state(self.conn, key, MAX_SEND_ATTEMPTS if no_tg else attempts + 1)
                self.conn.commit()
                return rep
            rep = await asyncio.to_thread(make)      # DB work off the event loop (the collector shares the file)
            if self.tg is None or not self.tg.enabled:
                log.info("market %s report for %s stored (Telegram not configured)", kind, start)
                continue
            ok = await send_report(self.conn, self.tg, rep["id"])
            log.info("market %s report for %s %s", kind, start, "sent" if ok else "NOT sent (will retry)")

    async def run(self) -> None:
        if not self.conn.execute("SELECT 1 FROM mc_daily_metrics LIMIT 1").fetchone():
            log.info("market: no data yet - backfilling all history")
            await self.fetch(backfill=True)
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 - never let the module stop the app
                log.exception("market scheduler tick failed")
            await asyncio.sleep(60)
