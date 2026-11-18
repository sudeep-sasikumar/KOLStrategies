"""Period maths for Market Conditions. Pure functions over {date: value} series (UTC days).

- Day: one complete UTC day. Week: Monday-Sunday UTC. Month: calendar month UTC. Only completed periods.
- Volumes (flow metrics) are summed over the period and need every day present; supply and price (stock
  metrics) use the value on the period's last day.
"""
from __future__ import annotations

from datetime import date, timedelta

FLOW = {"dex_volume_usd", "launchpad_volume_usd"}
AVG_N = {"daily": 7, "weekly": 4, "monthly": 3}          # "change vs average" looks back this many periods
HIGHLOW_N = {"weekly": 26, "monthly": 12}
UNIT = {"daily": "day", "weekly": "week", "monthly": "month"}


def period_of(kind: str, d: date) -> tuple[date, date]:
    if kind == "daily":
        return d, d
    if kind == "weekly":
        s = d - timedelta(days=d.weekday())
        return s, s + timedelta(days=6)
    if kind == "monthly":
        s = d.replace(day=1)
        return s, shift("monthly", s, 1) - timedelta(days=1)
    raise ValueError(kind)


def shift(kind: str, start: date, n: int) -> date:
    """Start of the period n periods after (n < 0: before) the one starting at `start`."""
    if kind == "daily":
        return start + timedelta(days=n)
    if kind == "weekly":
        return start + timedelta(days=7 * n)
    m = start.year * 12 + (start.month - 1) + n
    return date(m // 12, m % 12 + 1, 1)


def last_completed(kind: str, today: date) -> date:
    """Start of the latest period that ended before `today` (UTC)."""
    yesterday = today - timedelta(days=1)
    start, end = period_of(kind, yesterday)
    return start if end <= yesterday else shift(kind, start, -1)


def value(series: dict[date, float], metric: str, kind: str, start: date) -> float | None:
    s, e = period_of(kind, start)
    if metric in FLOW:
        days = [s + timedelta(days=i) for i in range((e - s).days + 1)]
        if any(d not in series for d in days):
            return None                              # incomplete period: never report a partial sum
        return sum(series[d] for d in days)
    return series.get(e)


def pct(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return (a / b - 1) * 100


def label(change_vs_avg: float | None, threshold: float) -> str | None:
    if change_vs_avg is None:
        return None
    if change_vs_avg > threshold:
        return "Rising"
    if change_vs_avg < -threshold:
        return "Falling"
    return "Flat"


def streak(series, metric: str, kind: str, start: date, limit: int = 120) -> int:
    """+n: risen n periods in a row up to `start`; -n: fallen n in a row; 0: unknown or unchanged."""
    n, sign = 0, 0
    cur = value(series, metric, kind, start)
    for k in range(1, limit + 1):
        prev = value(series, metric, kind, shift(kind, start, -k))
        if cur is None or prev is None or cur == prev:
            break
        s = 1 if cur > prev else -1
        if sign and s != sign:
            break
        sign, n, cur = s, n + 1, prev
    return sign * n


def stats(series, metric: str, kind: str, start: date, threshold: float) -> dict:
    v = value(series, metric, kind, start)
    prev = value(series, metric, kind, shift(kind, start, -1))
    back = [value(series, metric, kind, shift(kind, start, -k)) for k in range(1, AVG_N[kind] + 1)]
    back = [x for x in back if x is not None]
    avg = sum(back) / len(back) if back else None
    out = {"value": v, "prev": prev, "chg_prev": pct(v, prev), "avg": avg, "avg_n": len(back),
           "chg_avg": pct(v, avg), "streak": streak(series, metric, kind, start)}
    out["label"] = label(out["chg_avg"], threshold)
    if kind in HIGHLOW_N:
        pts = [(shift(kind, start, -k), value(series, metric, kind, shift(kind, start, -k)))
               for k in range(HIGHLOW_N[kind])]
        pts = [(d, x) for d, x in pts if x is not None]
        if pts:
            hi = max(pts, key=lambda p: p[1])
            lo = min(pts, key=lambda p: p[1])
            out.update(high=hi[1], high_start=hi[0].isoformat(), low=lo[1], low_start=lo[0].isoformat(),
                       pct_from_high=pct(v, hi[1]), pct_from_low=pct(v, lo[1]), window=len(pts))
    return out


def shares(by_chain: dict[str, dict[date, float]], kind: str, start: date) -> dict:
    """Each chain's share (%) of the tracked chains' DEX volume, and its change in points vs the previous period."""
    def at(s):
        vals = {c: value(ser, "dex_volume_usd", kind, s) for c, ser in by_chain.items()}
        total = sum(v for v in vals.values() if v is not None)
        return {c: (v / total * 100 if v is not None and total else None) for c, v in vals.items()}, total
    now, total = at(start)
    before, _ = at(shift(kind, start, -1))
    return {"total": total, "chains": {c: {"share": now[c], "share_prev": before[c],
                                           "share_chg": (now[c] - before[c]) if now[c] is not None
                                           and before[c] is not None else None} for c in by_chain}}


def headline(labels: list[str | None]) -> tuple[str, str]:
    """(emoji, text) from the three trench labels: Pump.fun bonding curve, PumpSwap, Solana DEX."""
    if any(x is None for x in labels):
        return "🟡", "Mixed"                         # a trench metric is missing: no direction claimed
    rising = labels.count("Rising")
    falling = labels.count("Falling")
    if rising == 3:
        return "🟢", "Trenches heating up"
    if rising >= 2 and falling == 0:
        return "🟢", "Trenches improving"
    if falling == 3:
        return "🔴", "Trenches cold"
    if falling >= 2 and rising == 0:
        return "🔴", "Trenches cooling"
    return "🟡", "Mixed"
