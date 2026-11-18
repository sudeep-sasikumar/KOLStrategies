"""Dashboard API for the Market Conditions page (registered by kol/web.py). Reads through read-only
connections; the only writes are manual metrics and the "send to Telegram" button."""
from __future__ import annotations

import asyncio
import csv
import io
import json
import re
import time
from datetime import date, timedelta

from aiohttp import web

from .. import db
from . import calc, fetch, reports, scheduler, settings, store

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
METRIC_RE = re.compile(r"^[A-Za-z0-9 _.%/()\-]{1,60}$")
N_PERIODS = {"daily": 90, "weekly": 52, "monthly": 24}


def _series_payload(conn, cfg, kind: str) -> dict:
    last = calc.last_completed(kind, fetch.utc_today())
    starts = [calc.shift(kind, last, -k) for k in range(N_PERIODS[kind] - 1, -1, -1)]
    data = reports._load(conn, cfg)

    def vals(metric, ser):
        return [calc.value(ser, metric, kind, s) for s in starts]
    shares = {c: [] for c in cfg["dex_chains"]}
    for s in starts:
        sh = calc.shares(data["dex"], kind, s)["chains"]
        for c in shares:
            shares[c].append(sh[c]["share"])
    return {
        "kind": kind, "periods": [s.isoformat() for s in starts],
        "launchpads": {e: vals("launchpad_volume_usd", ser) for e, ser in data["launch"].items()},
        "solana_dex": vals("dex_volume_usd", data["dex"].get("Solana", {})),
        "dex": {c: vals("dex_volume_usd", ser) for c, ser in data["dex"].items()},
        "shares": shares,
        "stable": {c: vals("stablecoin_supply_usd", ser) for c, ser in data["stable"].items()},
        "price": {p: vals("price_usd", ser) for p, ser in data["price"].items()},
    }


def _overview(conn, cfg) -> dict:
    day = calc.last_completed("daily", fetch.utc_today())
    rep = reports.compute(conn, cfg, "daily", day)
    data = reports._load(conn, cfg)
    spark_days = [day - timedelta(days=k) for k in range(29, -1, -1)]

    def spark(ser):
        return [ser.get(d) for d in spark_days]
    sol_st, sol_px = rep["stable"].get("Solana", {}), rep["price"].get("SOL", {})
    cards = [{"name": t["name"], "value": t["value"], "label": t["label"], "chg_avg": t["chg_avg"],
              "spark": spark(reports._ser(data, t["metric"], t["entity"]))} for t in rep["trench"]]
    cards.append({"name": "Solana stablecoins", "value": sol_st.get("value"), "label": sol_st.get("label"),
                  "chg_avg": sol_st.get("chg_avg"), "spark": spark(data["stable"].get("Solana", {}))})
    cards.append({"name": "SOL price", "value": sol_px.get("value"), "label": sol_px.get("label"),
                  "chg_avg": sol_px.get("chg_avg"), "price": True, "spark": spark(data["price"].get("SOL", {}))})
    return {"date": day.isoformat(), "headline": rep["headline"], "cards": cards, "missing": rep["missing"],
            "threshold_pct": cfg["label_threshold_pct"]}


def _health(conn, cfg) -> dict:
    srcs = []
    for code, s in cfg["sources"].items():
        last_ok = conn.execute("SELECT MAX(fetched_at_utc) FROM mc_raw_snapshots WHERE source=? AND error IS NULL",
                               (code,)).fetchone()[0]
        errs = [{"at": r[0], "key": r[1], "error": r[2]} for r in conn.execute(
            "SELECT fetched_at_utc, key, error FROM mc_raw_snapshots WHERE source=? AND error IS NOT NULL "
            "ORDER BY id DESC LIMIT 3", (code,))]
        srcs.append({"code": code, "name": s["name"], "enabled": s.get("enabled", True), "note": s.get("note", ""),
                     "last_ok": last_ok, "errors": errs})
    runs = [{"started": r[0], "finished": r[1], "kind": r[2], "ok": len(json.loads(r[3] or "[]")),
             "failed": json.loads(r[4] or "[]"), "rows": r[5]} for r in conn.execute(
        "SELECT started_at_utc, finished_at_utc, kind, ok_sources, failed_sources, rows_upserted FROM mc_fetch_log "
        "ORDER BY id DESC LIMIT 10")]
    rng = conn.execute("SELECT MIN(date_utc), MAX(date_utc), COUNT(*) FROM mc_daily_metrics").fetchone()
    return {"sources": srcs, "runs": runs, "first_day": rng[0], "last_day": rng[1], "rows": rng[2]}


def add_routes(app: web.Application, settings_, sched: "scheduler.MarketScheduler | None") -> None:
    cfg = settings.load()
    cache: dict = {}

    def ro():
        conn = db.connect(settings_.db_path, readonly=True)
        return conn

    async def run_ro(fn, *args, cache_key=None, ttl=60):
        if cache_key and cache_key in cache and time.time() - cache[cache_key][0] < ttl:
            return cache[cache_key][1]

        def go():
            conn = ro()
            try:
                return fn(conn, *args)
            finally:
                conn.close()
        out = await asyncio.to_thread(go)
        if cache_key:
            cache[cache_key] = (time.time(), out)
        return out

    async def overview(_r):
        return web.json_response(await run_ro(_overview, cfg, cache_key="overview"))

    async def series(request):
        kind = request.query.get("period", "daily")
        if kind not in N_PERIODS:
            raise web.HTTPBadRequest()
        return web.json_response(await run_ro(_series_payload, cfg, kind, cache_key=("series", kind)))

    async def report_list(_r):
        def q(conn):
            return [dict(zip(("id", "period_type", "start", "end", "generated", "text", "sent"), r)) for r in conn.execute(
                "SELECT id, period_type, period_start_utc, period_end_utc, generated_at_utc, summary_text, "
                "telegram_sent FROM mc_reports ORDER BY generated_at_utc DESC LIMIT 200")]
        return web.json_response(await run_ro(q))

    async def report_send(request):
        if sched is None or sched.tg is None or not sched.tg.enabled:
            return web.json_response({"error": "Telegram is not configured"}, status=400)
        try:
            rid = int(request.match_info["id"])
        except ValueError:
            raise web.HTTPBadRequest()
        ok = await scheduler.send_report(sched.conn, sched.tg, rid)
        return web.json_response({"ok": ok}, status=200 if ok else 502)

    async def health(_r):
        out = await run_ro(_health, cfg)
        out["fetch_running"] = bool(sched and sched.running)
        return web.json_response(out)

    async def manual_list(_r):
        def q(conn):
            return [dict(zip(("id", "date_utc", "metric", "value", "source_note", "entered"), r)) for r in conn.execute(
                "SELECT id, date_utc, metric, value, source_note, entered_at_utc FROM mc_manual_metrics "
                "ORDER BY date_utc DESC, id DESC LIMIT 500")]
        return web.json_response(await run_ro(q))

    async def manual_add(request):
        try:
            j = await request.json()
            d = str(j.get("date_utc", ""))
            metric = str(j.get("metric", "")).strip()
            value = float(j.get("value"))
            note = str(j.get("source_note", "")).strip()[:200]
        except (ValueError, TypeError):
            return web.json_response({"error": "date, metric and a numeric value are required"}, status=400)
        if not DATE_RE.match(d) or not METRIC_RE.match(metric):
            return web.json_response({"error": "date must be YYYY-MM-DD; metric: letters, digits, spaces"}, status=400)
        date.fromisoformat(d)

        def w():
            conn = db.connect(settings_.db_path)
            try:
                store.init(conn)
                conn.execute("INSERT INTO mc_manual_metrics (date_utc, metric, value, source_note, entered_at_utc) "
                             "VALUES (?,?,?,?,?)", (d, metric, value, note, time.time()))
                conn.commit()
            finally:
                conn.close()
        await asyncio.to_thread(w)
        return web.json_response({"ok": True})

    async def csv_dl(request):
        frm, to = request.query.get("from", ""), request.query.get("to", "")
        if not (DATE_RE.match(frm) and DATE_RE.match(to)):
            raise web.HTTPBadRequest(text="from and to must be YYYY-MM-DD")

        def q(conn):
            buf = io.StringIO()
            wr = csv.writer(buf)
            wr.writerow(["date_utc", "metric", "entity", "value", "source", "updated_at_utc"])
            for r in conn.execute("SELECT date_utc, metric, entity, value, source, updated_at_utc FROM mc_daily_metrics "
                                  "WHERE date_utc BETWEEN ? AND ? ORDER BY date_utc, metric, entity", (frm, to)):
                wr.writerow(r)
            return buf.getvalue()
        body = await run_ro(q)
        return web.Response(text=body, content_type="text/csv", headers={
            "Content-Disposition": f'attachment; filename="mc_daily_metrics_{frm}_{to}.csv"'})

    app.add_routes([
        web.get("/api/market/overview", overview), web.get("/api/market/series", series),
        web.get("/api/market/reports", report_list), web.post("/api/market/reports/{id}/send", report_send),
        web.get("/api/market/health", health), web.get("/api/market/manual", manual_list),
        web.post("/api/market/manual", manual_add), web.get("/api/market/csv", csv_dl),
    ])
