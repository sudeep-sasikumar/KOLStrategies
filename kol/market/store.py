"""mc_* tables in the project's SQLite database. Only the Market Conditions module uses them."""
from __future__ import annotations

import json
import sqlite3
import time
import zlib
from datetime import date

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS mc_raw_snapshots (
    id INTEGER PRIMARY KEY, fetched_at_utc REAL, source TEXT, key TEXT, http_status INTEGER,
    response_json BLOB, error TEXT);  -- response_json is zlib-compressed UTF-8 JSON (raw_json() reads it)
CREATE INDEX IF NOT EXISTS mc_raw_at ON mc_raw_snapshots(fetched_at_utc);
CREATE TABLE IF NOT EXISTS mc_daily_metrics (
    date_utc TEXT, metric TEXT, entity TEXT, value REAL, source TEXT, updated_at_utc REAL,
    PRIMARY KEY (date_utc, metric, entity));
CREATE INDEX IF NOT EXISTS mc_daily_entity ON mc_daily_metrics(metric, entity, date_utc);
CREATE TABLE IF NOT EXISTS mc_reports (
    id INTEGER PRIMARY KEY, period_type TEXT, period_start_utc TEXT, period_end_utc TEXT,
    generated_at_utc REAL, summary_text TEXT, report_json TEXT, telegram_sent INTEGER DEFAULT 0,
    UNIQUE (period_type, period_start_utc));
CREATE TABLE IF NOT EXISTS mc_manual_metrics (
    id INTEGER PRIMARY KEY, date_utc TEXT, metric TEXT, value REAL, source_note TEXT, entered_at_utc REAL);
CREATE INDEX IF NOT EXISTS mc_manual_date ON mc_manual_metrics(date_utc);
CREATE TABLE IF NOT EXISTS mc_fetch_log (
    id INTEGER PRIMARY KEY, started_at_utc REAL, finished_at_utc REAL, kind TEXT,
    ok_sources TEXT, failed_sources TEXT, rows_upserted INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS mc_bridge_flows (
    date_utc TEXT, chain TEXT, deposit_usd REAL, withdraw_usd REAL, updated_at_utc REAL,
    PRIMARY KEY (date_utc, chain));
CREATE TABLE IF NOT EXISTS mc_state (k TEXT PRIMARY KEY, v TEXT);
"""


def init(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO mc_state VALUES ('schema_version', ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                 (str(SCHEMA_VERSION),))
    conn.commit()


def save_raw(conn, source: str, key: str, status: int | None, body: str | None, error: str | None) -> None:
    blob = zlib.compress(body.encode("utf-8"), 6) if body else None
    conn.execute("INSERT INTO mc_raw_snapshots (fetched_at_utc, source, key, http_status, response_json, error) "
                 "VALUES (?,?,?,?,?,?)", (time.time(), source, key, status, blob, error))


def raw_json(blob: bytes | None) -> str | None:
    return zlib.decompress(blob).decode("utf-8") if blob else None


def upsert_metrics(conn, rows: list[tuple[str, str, str, float, str]]) -> int:
    """rows: (date_utc, metric, entity, value, source)."""
    now = time.time()
    conn.executemany(
        "INSERT INTO mc_daily_metrics (date_utc, metric, entity, value, source, updated_at_utc) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(date_utc, metric, entity) DO UPDATE SET value=excluded.value, source=excluded.source, "
        "updated_at_utc=excluded.updated_at_utc", [r + (now,) for r in rows])
    return len(rows)


def series(conn, metric: str, entity: str) -> dict[date, float]:
    return {date.fromisoformat(r[0]): r[1] for r in conn.execute(
        "SELECT date_utc, value FROM mc_daily_metrics WHERE metric=? AND entity=? ORDER BY date_utc",
        (metric, entity))}


def get_state(conn, k: str, default=None):
    r = conn.execute("SELECT v FROM mc_state WHERE k=?", (k,)).fetchone()
    return json.loads(r[0]) if r else default


def set_state(conn, k: str, v) -> None:
    conn.execute("INSERT INTO mc_state VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v)))


def failures_since(conn, since: float) -> list[str]:
    """Sources that failed in any fetch run that finished after `since` (for the report's warning line)."""
    out: list[str] = []
    for r in conn.execute("SELECT failed_sources FROM mc_fetch_log WHERE finished_at_utc>=? ORDER BY id", (since,)):
        for f in json.loads(r[0] or "[]"):
            if f not in out:
                out.append(f)
    return out


def manual_between(conn, start: date, end: date) -> list[dict]:
    return [dict(zip(("date_utc", "metric", "value", "source_note"), r)) for r in conn.execute(
        "SELECT date_utc, metric, value, source_note FROM mc_manual_metrics WHERE date_utc BETWEEN ? AND ? "
        "ORDER BY date_utc, metric", (start.isoformat(), end.isoformat()))]
