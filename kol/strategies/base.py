"""Strategy = a set of board columns, each with filters, evaluated on every token we follow.

Adding a strategy: describe it in a new module (see daumen.py) and list it in strategies/__init__.py.
The dashboard gets a tab for it automatically, and the collector records its hits and misses.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..models import Token

# where a filter's input comes from: shown on the dashboard so you know how far to trust it
EXACT, APPROX, ESTIMATE = "exact", "approx", "estimate"


@dataclass(frozen=True)
class Filter:
    key: str
    label: str
    feature: str            # key in features()
    op: str                 # "<=", ">=", "is_false", "excludes_any"
    value: object = None
    quality: str = EXACT
    audit: bool = False     # needs an on-chain look-up (holders, dev %, snipers, fees)
    unknown_ok: bool = False
    note: str = ""

    def check(self, v) -> bool | None:
        """True/False, or None when the input is not known yet."""
        if self.op == "excludes_any":
            text = (v or "").lower()
            return not any(k.lower() in text for k in (self.value or ()))
        if v is None:
            return True if self.unknown_ok else None
        if self.op == "<=":
            return v <= self.value
        if self.op == ">=":
            return v >= self.value
        if self.op == "is_false":
            return not v
        raise ValueError(self.op)

    def describe(self) -> str:
        if self.op == "<=":
            return f"max {self.value:,}" if isinstance(self.value, (int, float)) else f"max {self.value}"
        if self.op == ">=":
            return f"min {self.value:,}" if isinstance(self.value, (int, float)) else f"min {self.value}"
        if self.op == "is_false":
            return "hide"
        if self.op == "excludes_any":
            return "exclude: " + ", ".join(self.value or ()) if self.value else "(none)"
        return str(self.value)


@dataclass(frozen=True)
class Column:
    key: str
    title: str
    stage: str              # "new" (any token on the bonding curve), "bonding" (not migrated), "migrated"
    horizon_s: int          # stop evaluating this long after the stage started (creation / migration)
    filters: tuple[Filter, ...]
    audit_refresh_s: int = 90
    audit_max: int = 6
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class Strategy:
    key: str
    name: str
    author: str
    source_url: str
    platform: str
    summary: str
    columns: tuple[Column, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)


def features(t: Token, now: float, sol_usd: float | None) -> dict:
    age_min = (now - t.created_at) / 60 if t.created_at else None
    return {
        "age_min": age_min,
        "mc_usd": t.mc_usd,
        "vol_usd": t.vol_usd,
        "holders": t.holders,
        "dev_pct": t.dev_pct,
        "snipers_pct": t.snipers_pct,
        "top10_pct": t.top10_pct,
        "fees_sol": t.fees_sol,
        "mayhem": None if t.mayhem is None else bool(t.mayhem),
        "text": f"{t.name} {t.symbol}",
        "migrated": t.migrated_at is not None,
        "has_socials": t.has_socials,
        "progress_pct": t.progress_pct,
        "buys": t.buys,
        "sells": t.sells,
        "tx_count": t.tx_count,
        "bundle_buyers": t.bundle_buyers,
        "snipers": t.snipers,
        "dev_initial_pct": t.dev_initial_pct,
        "sol_usd": sol_usd,
    }


def in_stage(col: Column, t: Token, now: float) -> bool:
    if col.stage == "migrated":
        return t.migrated_at is not None and now - t.migrated_at <= col.horizon_s
    if t.migrated_at is not None or not t.created_at:
        return False
    return now - t.created_at <= col.horizon_s


@dataclass
class Result:
    passed: bool
    failed: list[str]        # filter keys that failed
    unknown: list[str]       # filter keys whose input is not known yet
    cheap_ok: bool           # every filter that needs no on-chain look-up passes


def evaluate(col: Column, feats: dict) -> Result:
    failed, unknown, cheap_ok = [], [], True
    for f in col.filters:
        r = f.check(feats.get(f.feature))
        if r is None:
            unknown.append(f.key)
        elif not r:
            failed.append(f.key)
            if not f.audit:
                cheap_ok = False
    return Result(passed=not failed and not unknown, failed=failed, unknown=unknown, cheap_ok=cheap_ok)
