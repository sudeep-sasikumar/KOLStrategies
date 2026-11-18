"""SQLite storage. One writer (the collector); the dashboard reads through its own connections."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .models import HIT_FIELDS, TOKEN_FIELDS, Hit, Token


def connect(path: Path, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30, check_same_thread=False)
    else:
        conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def init(conn: sqlite3.Connection) -> None:
    conn.execute(f"CREATE TABLE IF NOT EXISTS tokens (mint TEXT PRIMARY KEY, "
                 f"{', '.join(f for f in TOKEN_FIELDS if f != 'mint')})")
    have = {r[1] for r in conn.execute("PRAGMA table_info(tokens)")}
    for f in TOKEN_FIELDS:                       # columns added in later versions
        if f not in have:
            conn.execute(f"ALTER TABLE tokens ADD COLUMN {f}")
    conn.execute(f"CREATE TABLE IF NOT EXISTS hits (id INTEGER PRIMARY KEY, {', '.join(HIT_FIELDS)}, "
                 "UNIQUE(strategy, col, mint))")
    have = {r[1] for r in conn.execute("PRAGMA table_info(hits)")}
    for f in HIT_FIELDS:
        if f not in have:
            conn.execute(f"ALTER TABLE hits ADD COLUMN {f}")
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS tokens_done ON tokens(done);
        CREATE INDEX IF NOT EXISTS tokens_first_seen ON tokens(first_seen);
        CREATE INDEX IF NOT EXISTS hits_at ON hits(strategy, col, hit_at);
        CREATE TABLE IF NOT EXISTS evals (strategy TEXT, col TEXT, mint TEXT, at REAL, n_failed INTEGER,
            failed TEXT, PRIMARY KEY (strategy, col, mint));
        CREATE TABLE IF NOT EXISTS state (k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE IF NOT EXISTS events (ts REAL, level TEXT, msg TEXT);
        CREATE INDEX IF NOT EXISTS events_ts ON events(ts);
        CREATE TABLE IF NOT EXISTS coverage (hour INTEGER PRIMARY KEY, creates INTEGER, ws_up_s REAL);
    """)
    conn.commit()


def save_tokens(conn: sqlite3.Connection, toks: list[Token]) -> None:
    if not toks:
        return
    cols = ", ".join(TOKEN_FIELDS)
    qs = ", ".join("?" for _ in TOKEN_FIELDS)
    upd = ", ".join(f"{f}=excluded.{f}" for f in TOKEN_FIELDS if f != "mint")
    conn.executemany(f"INSERT INTO tokens ({cols}) VALUES ({qs}) ON CONFLICT(mint) DO UPDATE SET {upd}",
                     [tuple(getattr(t, f) for f in TOKEN_FIELDS) for t in toks])


def load_active(conn: sqlite3.Connection) -> list[Token]:
    rows = conn.execute(f"SELECT {', '.join(TOKEN_FIELDS)} FROM tokens WHERE done=0").fetchall()
    return [Token(**dict(r)) for r in rows]


def save_hits(conn: sqlite3.Connection, hits: list[Hit]) -> None:
    for h in hits:
        vals = tuple(getattr(h, f) for f in HIT_FIELDS)
        if h.id is None:
            cur = conn.execute(f"INSERT OR IGNORE INTO hits ({', '.join(HIT_FIELDS)}) VALUES "
                               f"({', '.join('?' for _ in HIT_FIELDS)})", vals)
            h.id = cur.lastrowid or conn.execute(
                "SELECT id FROM hits WHERE strategy=? AND col=? AND mint=?", (h.strategy, h.col, h.mint)).fetchone()[0]
        else:
            conn.execute(f"UPDATE hits SET {', '.join(f'{f}=?' for f in HIT_FIELDS)} WHERE id=?", vals + (h.id,))


def load_open_hits(conn: sqlite3.Connection, since: float) -> list[Hit]:
    rows = conn.execute("SELECT * FROM hits WHERE hit_at>=?", (since,)).fetchall()
    return [Hit(**dict(r)) for r in rows]


def save_evals(conn: sqlite3.Connection, evals: list[tuple]) -> None:
    """evals: (strategy, col, mint, at, n_failed, failed_json). Keeps each token's closest miss."""
    conn.executemany(
        "INSERT INTO evals (strategy, col, mint, at, n_failed, failed) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(strategy, col, mint) DO UPDATE SET at=excluded.at, n_failed=excluded.n_failed, "
        "failed=excluded.failed WHERE excluded.n_failed <= evals.n_failed", evals)


def log_event(conn: sqlite3.Connection, ts: float, level: str, msg: str) -> None:
    conn.execute("INSERT INTO events VALUES (?,?,?)", (ts, level, msg[:500]))


def get_state(conn: sqlite3.Connection, k: str, default=None):
    r = conn.execute("SELECT v FROM state WHERE k=?", (k,)).fetchone()
    return json.loads(r[0]) if r else default


def set_state(conn: sqlite3.Connection, k: str, v) -> None:
    conn.execute("INSERT INTO state VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v)))
