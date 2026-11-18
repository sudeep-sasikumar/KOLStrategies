"""Read-only numbers for the dashboard: how each column's hits did, which runners it missed and why,
which single filter removes the most noise for the fewest runners, and what the winners had in common."""
from __future__ import annotations

import json
import sqlite3
import time
from collections import Counter, defaultdict

from . import config as C
from .strategies.base import Strategy
from .util import median

# pump.fun launches only (see strategies.base.in_universe); "t" is the tokens table alias
UNIVERSE = "(t.pool='pump' OR (COALESCE(t.pool,'')='' AND t.mint LIKE '%pump'))"
RUNNER = (f"(COALESCE(t.peak_mc,0) >= {C.RUNNER_MC_USD} AND COALESCE(t.peak_mc,0) >= "
          f"{C.RUNNER_MIN_MULT} * COALESCE(t.mc_create_usd,0) AND COALESCE(t.vol_usd,0) >= {C.RUNNER_MIN_VOL_USD})")

SESSIONS = (("Asia", 22, 7), ("Europe", 7, 13), ("EU+US overlap", 13, 16), ("US", 16, 22))
FEATURES = (
    ("age_min", "Age at hit (min)"), ("mc_usd", "Market cap ($)"), ("vol_usd", "Volume ($)"),
    ("holders", "Holders"), ("dev_pct", "Dev holding %"), ("snipers_pct", "Snipers %"),
    ("insiders_pct", "Insiders % (creation-slot buyers)"), ("snipers", "Sniper wallets"), ("bundle_buyers", "Bundle buyers (creation slot)"),
    ("top10_pct", "Top 10 %"), ("fees_sol", "Total fees (SOL, est.)"), ("tx_count", "Transactions"),
    ("buy_ratio", "Buys / (buys + sells)"), ("dev_initial_pct", "Dev initial buy %"),
    ("progress_pct", "Bonding progress %"), ("has_socials", "Has X / Telegram / website (share)"),
    ("has_community", "Has pump.fun community link (share)"),
)


def session_of(hour: int) -> str:
    for name, a, b in SESSIONS:
        if (a <= hour < b) if a < b else (hour >= a or hour < b):
            return name
    return "?"


def _mult(h) -> float | None:
    if h["peak_mc"] and h["mc_at_hit"]:
        return h["peak_mc"] / h["mc_at_hit"]
    return None


def _rate(xs: list[bool]) -> float | None:
    return sum(xs) / len(xs) * 100 if xs else None


def strategy_report(conn: sqlite3.Connection, strat: Strategy, days: float) -> dict:
    now = time.time()
    since = now - days * 86400
    out = {"days": days, "runner_mc": C.RUNNER_MC_USD, "runner_rule": C.RUNNER_RULE, "columns": {}}
    coverage = conn.execute("SELECT COALESCE(SUM(creates),0) c, COALESCE(SUM(ws_up_s),0) up FROM coverage "
                            "WHERE hour>=?", (int(since // 3600),)).fetchone()
    tracked_s = min(now - since, max(1.0, now - (conn.execute("SELECT MIN(first_seen) FROM tokens").fetchone()[0]
                                                 or now)))
    out["coverage"] = {"creates": coverage["c"], "uptime_pct": min(100.0, coverage["up"] / tracked_s * 100)
                       if tracked_s > 60 else None}
    created = conn.execute(f"SELECT COUNT(*) FROM tokens t WHERE seen_create=1 AND first_seen>=? AND {UNIVERSE}",
                           (since,)).fetchone()[0]
    other = conn.execute(f"SELECT COUNT(*) FROM tokens t WHERE seen_create=1 AND first_seen>=? AND NOT {UNIVERSE}",
                         (since,)).fetchone()[0]
    runners = {r["mint"]: dict(r) for r in conn.execute(
        "SELECT mint, name, symbol, peak_mc, peak_at, migrated_at, created_at, first_seen, mc_1h FROM tokens t "
        f"WHERE first_seen>=? AND seen_create=1 AND {UNIVERSE} AND {RUNNER}", (since,))}
    out["universe"] = {"created": created, "runners": len(runners), "other_launchpads": other,
                       "runner_rate": len(runners) / created * 100 if created else None,
                       "migrated": conn.execute(f"SELECT COUNT(*) FROM tokens t WHERE migrated_at>=? AND {UNIVERSE}",
                                                (since,)).fetchone()[0]}
    for col in strat.columns:
        out["columns"][col.key] = _column_report(conn, strat, col, since, now, runners)
    out["daily"] = _daily(conn, strat, since)
    return out


def _column_report(conn, strat, col, since, now, runners) -> dict:
    rows = conn.execute(
        f"SELECT h.*, t.name, t.symbol, t.peak_mc AS tok_peak, t.migrated_at, {RUNNER} AS is_runner FROM hits h "
        f"JOIN tokens t ON t.mint=h.mint WHERE h.strategy=? AND h.col=? AND h.hit_at>=? AND {UNIVERSE} "
        "ORDER BY h.hit_at DESC",
        (strat.key, col.key, since)).fetchall()
    hours = max((now - since) / 3600, 1e-9)
    first = conn.execute("SELECT MIN(hit_at) FROM hits WHERE strategy=? AND col=?", (strat.key, col.key)).fetchone()[0]
    if first:
        hours = max(min(hours, (now - first) / 3600), 1 / 60)
    matured = [r for r in rows if now - r["hit_at"] >= 3600]
    mults = [_mult(r) for r in matured]
    res = {
        "hits": len(rows),
        "hits_per_hour": len(rows) / hours,
        "matured_1h": len(matured),
        "matured_24h": sum(1 for r in rows if now - r["hit_at"] >= 86400),
        "rate_2x": _rate([(m or 0) >= 2 for m in mults]),
        "rate_5x": _rate([(m or 0) >= 5 for m in mults]),
        "rate_10x": _rate([(m or 0) >= 10 for m in mults]),
        "rate_runner": _rate([bool(r["is_runner"]) for r in matured]),
        "rate_migrated": _rate([bool(r["migrated_at"]) for r in matured]) if col.stage != "migrated" else None,
        "median_mult": median(mults),
        "median_1h": median([r["mc_1h"] / r["mc_at_hit"] for r in matured if r["mc_1h"] and r["mc_at_hit"]]),
    }
    # recall: of the runners this column could have shown, how many did it catch
    hit_mints = {r["mint"] for r in conn.execute("SELECT mint FROM hits WHERE strategy=? AND col=? AND hit_at>=?",
                                                 (strat.key, col.key, since - 86400))}
    pool = {m: r for m, r in runners.items() if col.stage != "migrated" or r["migrated_at"]}
    caught = [m for m in pool if m in hit_mints]
    missed = [m for m in pool if m not in hit_mints]
    res["runners_in_pool"] = len(pool)
    res["runners_caught"] = len(caught)
    res["recall"] = len(caught) / len(pool) * 100 if pool else None
    res["hits_per_runner"] = len(rows) / len(caught) if caught else None
    reasons = Counter()
    missed_rows = []
    evals = _evals(conn, strat.key, col.key, missed)
    for m in sorted(missed, key=lambda m: -(pool[m]["peak_mc"] or 0))[:300]:
        failed = evals.get(m)
        keys = failed if failed is not None else ["(not evaluated)"]
        if failed is not None and fast_migration(col, failed, pool[m]["created_at"], pool[m]["migrated_at"]):
            keys = [FAST]
        for k in keys:
            reasons[k] += 1
        if len(missed_rows) < 40:
            r = pool[m]
            missed_rows.append({"mint": m, "name": r["name"], "symbol": r["symbol"], "peak_mc": r["peak_mc"],
                                "failed": [_label(k, labels) if k == FAST else k for k in keys]})
    labels = {f.key: f.label for f in col.filters}
    res["missed_reasons"] = [{"key": k, "label": _label(k, labels), "n": n} for k, n in reasons.most_common()]
    res["missed"] = missed_rows
    res["filter_impact"] = _filter_impact(conn, strat.key, col, since, labels)
    res["features"] = _feature_compare(matured)
    res["sessions"] = _sessions(matured)
    res["recent"] = [_hit_row(r, now) for r in rows[:60]]
    return res


FAST = "migrated_fast"
FAST_LABEL = "Migrated before the on-chain check finished"


def fast_migration(col, failed: list[str], created_at, migrated_at) -> bool:
    """A bonding-curve column's miss that is not a filter failure: the token migrated (left the column) inside
    the column's window while its on-chain values (holders, dev %, snipers, fees...) were still unknown."""
    return (col.stage == "bonding" and any(k.endswith("?") for k in failed) and bool(created_at)
            and bool(migrated_at) and migrated_at - created_at <= col.horizon_s)


def _label(k: str, labels: dict) -> str:
    if k == FAST:
        return FAST_LABEL
    if k.endswith("?"):
        return labels.get(k[:-1], k[:-1]) + " (not checked yet)"
    return labels.get(k, k)


def _evals(conn, strat: str, col: str, mints: list[str]) -> dict[str, list[str]]:
    out = {}
    for i in range(0, len(mints), 500):
        chunk = mints[i:i + 500]
        q = f"SELECT mint, failed FROM evals WHERE strategy=? AND col=? AND mint IN ({','.join('?' * len(chunk))})"
        for r in conn.execute(q, (strat, col, *chunk)):
            out[r["mint"]] = json.loads(r["failed"] or "[]")
    return out


def _filter_impact(conn, strat: str, col, since: float, labels: dict) -> list[dict]:
    """Tokens that failed exactly one filter: what that filter alone removes (noise vs runners)."""
    agg: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for r in conn.execute(
            f"SELECT e.failed, {RUNNER} AS is_runner, t.migrated_at, t.created_at FROM evals e JOIN tokens t ON "
            f"t.mint=e.mint WHERE e.strategy=? AND e.col=? AND e.n_failed=1 AND e.at>=? AND {UNIVERSE}",
            (strat, col.key, since)):
        keys = json.loads(r["failed"] or "[]")
        if len(keys) != 1:
            continue
        if fast_migration(col, keys, r["created_at"], r["migrated_at"]):
            keys = [FAST]
        a = agg[keys[0]]
        a[0] += 1
        a[1] += int(bool(r["is_runner"]))
        a[2] += int(bool(r["migrated_at"]))
    return sorted(({"key": k, "label": _label(k, labels), "removed": a[0], "runners_removed": a[1],
                    "migrated_removed": a[2]} for k, a in agg.items()), key=lambda x: -x["removed"])


def _feature_compare(matured) -> list[dict]:
    win, lose = [], []
    for r in matured:
        try:
            snap = json.loads(r["snapshot"] or "{}")
        except ValueError:
            continue
        b, s = snap.get("buys"), snap.get("sells")
        snap["buy_ratio"] = b / (b + s) if b is not None and s is not None and (b + s) else None
        snap["has_socials"] = 1.0 if snap.get("has_socials") else 0.0
        snap["has_community"] = 1.0 if snap.get("has_community") else 0.0
        (win if (_mult(r) or 0) >= 2 else lose).append(snap)
    rows = []
    for key, label in FEATURES:
        w = [x.get(key) for x in win if x.get(key) is not None]
        l_ = [x.get(key) for x in lose if x.get(key) is not None]
        if key in ("has_socials", "has_community"):
            rows.append({"key": key, "label": label, "win": sum(w) / len(w) * 100 if w else None,
                         "lose": sum(l_) / len(l_) * 100 if l_ else None, "n_win": len(w), "n_lose": len(l_),
                         "pct": True})
        else:
            rows.append({"key": key, "label": label, "win": median(w), "lose": median(l_), "n_win": len(w),
                         "n_lose": len(l_)})
    return rows


def _sessions(matured) -> list[dict]:
    agg: dict[str, list] = {name: [] for name, _, _ in SESSIONS}
    for r in matured:
        agg[session_of(time.gmtime(r["hit_at"]).tm_hour)].append((_mult(r) or 0) >= 2)
    return [{"session": k, "hits": len(v), "rate_2x": _rate(v)} for k, v in agg.items()]


def _hit_row(r, now: float) -> dict:
    snap = json.loads(r["snapshot"] or "{}")
    return {
        "mint": r["mint"], "name": r["name"], "symbol": r["symbol"], "hit_at": r["hit_at"],
        "mc_at_hit": r["mc_at_hit"], "peak_mc": r["peak_mc"], "mult": _mult(r),
        "mc_5m": r["mc_5m"], "mc_1h": r["mc_1h"], "mc_24h": r["mc_24h"], "migrated": bool(r["migrated_at"]),
        "holders": snap.get("holders"), "dev_pct": snap.get("dev_pct"), "snipers_pct": snap.get("snipers_pct"),
        "fees_sol": snap.get("fees_sol"), "vol_usd": snap.get("vol_usd"), "age_min": snap.get("age_min"),
        "pending": now - r["hit_at"] < 3600,
    }


def _daily(conn, strat: Strategy, since: float) -> list[dict]:
    days: dict[str, dict] = defaultdict(lambda: {"created": 0, "runners": 0, "migrated": 0})
    for r in conn.execute(f"SELECT date(first_seen,'unixepoch') d, COUNT(*) n, SUM(CASE WHEN {RUNNER} THEN 1 ELSE 0 "
                          f"END) r FROM tokens t WHERE first_seen>=? AND seen_create=1 AND {UNIVERSE} GROUP BY d",
                          (since,)):
        days[r["d"]]["created"], days[r["d"]]["runners"] = r["n"], r["r"]
    for r in conn.execute(f"SELECT date(migrated_at,'unixepoch') d, COUNT(*) n FROM tokens t WHERE migrated_at>=? "
                          f"AND {UNIVERSE} GROUP BY d", (since,)):
        days[r["d"]]["migrated"] = r["n"]
    for r in conn.execute(f"SELECT date(h.hit_at,'unixepoch') d, h.col, COUNT(*) n FROM hits h JOIN tokens t ON "
                          f"t.mint=h.mint WHERE h.strategy=? AND h.hit_at>=? AND {UNIVERSE} GROUP BY d, h.col",
                          (strat.key, since)):
        days[r["d"]][f"hits_{r['col']}"] = r["n"]
    return [{"day": d, **v} for d, v in sorted(days.items(), reverse=True)]


def token_detail(conn: sqlite3.Connection, mint: str) -> dict | None:
    r = conn.execute("SELECT * FROM tokens WHERE mint=?", (mint,)).fetchone()
    if not r:
        return None
    t = dict(r)
    t.pop("sniper_list", None)
    t["hits"] = [dict(h) for h in conn.execute("SELECT strategy, col, hit_at, mc_at_hit, peak_mc, mc_5m, mc_1h, "
                                               "mc_24h FROM hits WHERE mint=?", (mint,))]
    t["evals"] = [dict(e) for e in conn.execute("SELECT strategy, col, at, n_failed, failed FROM evals WHERE mint=?",
                                                (mint,))]
    return t
