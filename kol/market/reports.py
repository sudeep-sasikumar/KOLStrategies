"""Daily / weekly / monthly Market Conditions reports. Fixed templates: the same data always gives the
same text, and every number comes from mc_daily_metrics (or mc_manual_metrics)."""
from __future__ import annotations

import html
import json
import time
from datetime import date, datetime, timezone

from . import calc, store

TRENCH = (("launchpad_volume_usd", "pump.fun", "Pump.fun bonding curve"),
          ("launchpad_volume_usd", "pumpswap", "PumpSwap"),
          ("dex_volume_usd", "Solana", "Solana DEX"))


# ---- formatting ------------------------------------------------------------------------------------
def usd(v: float | None) -> str:
    if v is None:
        return "n/a"
    a = abs(v)
    if a >= 1e9:
        return f"${v / 1e9:.2f}B"
    if a >= 1e6:
        return f"${v / 1e6:.0f}M" if a >= 1e7 else f"${v / 1e6:.1f}M"
    if a >= 1e3:
        return f"${v:,.0f}"
    return f"${v:.2f}"


def chg(p: float | None) -> str:
    if p is None:
        return "n/a"
    arrow = "▲" if p > 0 else ("▼" if p < 0 else "–")
    return f"{arrow} {abs(p):.1f}%"


def pts(p: float | None) -> str:
    if p is None:
        return "n/a"
    arrow = "▲" if p > 0 else ("▼" if p < 0 else "–")
    return f"{arrow} {abs(p):.1f} pts"


def day_label(d: date) -> str:
    return f"{d:%a} {d.day} {d:%b}"


def range_label(s: date, e: date) -> str:
    return f"{s.day} {s:%b}" + (f" {s.year}" if s.year != e.year else "") + f" – {e.day} {e:%b} {e.year}"


def month_label(d: date) -> str:
    return f"{d:%b %Y}"


def ordinal(n: int) -> str:
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def streak_text(s: int, unit: str) -> str:
    if s == 0:
        return "no change"
    word = "up" if s > 0 else "down"
    return f"{word} this {unit}" if abs(s) == 1 else f"{word} {abs(s)} {unit}s in a row"


# ---- data ------------------------------------------------------------------------------------------
def _load(conn, cfg) -> dict:
    data = {"dex": {c: store.series(conn, "dex_volume_usd", c) for c in cfg["dex_chains"]},
            "stable": {c: store.series(conn, "stablecoin_supply_usd", c) for c in cfg["stablecoin_chains"]},
            "launch": {e: store.series(conn, "launchpad_volume_usd", e) for e in cfg["launchpads"]},
            "price": {e: store.series(conn, "price_usd", e) for e in cfg["prices"]}}
    return data


def _ser(data, metric, entity):
    return {"dex_volume_usd": data["dex"], "launchpad_volume_usd": data["launch"],
            "stablecoin_supply_usd": data["stable"], "price_usd": data["price"]}[metric].get(entity, {})


def compute(conn, cfg: dict, kind: str, start: date) -> dict:
    """Every number the report uses, as JSON-friendly values."""
    th = cfg["label_threshold_pct"]
    data = _load(conn, cfg)
    s, e = calc.period_of(kind, start)
    rep: dict = {"period_type": kind, "start": s.isoformat(), "end": e.isoformat(), "threshold_pct": th}
    rep["trench"] = [{"metric": m, "entity": ent, "name": name,
                      **calc.stats(_ser(data, m, ent), m, kind, s, th)} for m, ent, name in TRENCH]
    rep["headline"] = calc.headline([t["label"] for t in rep["trench"]])
    rep["stable"] = {c: calc.stats(ser, "stablecoin_supply_usd", kind, s, th) for c, ser in data["stable"].items()}
    rep["price"] = {p: calc.stats(ser, "price_usd", kind, s, th) for p, ser in data["price"].items()}
    rep["chains"] = {c: calc.stats(ser, "dex_volume_usd", kind, s, th) for c, ser in data["dex"].items()}
    sh = calc.shares(data["dex"], kind, s)
    rep["share_total"] = sh["total"]
    for c, v in sh["chains"].items():
        rep["chains"][c].update(v)
    if kind == "monthly":                          # chain share over the last 6 months
        rep["share_trend"] = {"months": [calc.shift(kind, s, -k).isoformat() for k in range(5, -1, -1)],
                              "chains": {c: [calc.shares(data["dex"], kind, calc.shift(kind, s, -k))["chains"][c]["share"]
                                             for k in range(5, -1, -1)] for c in data["dex"]}}
    rep["manual"] = store.manual_between(conn, s, e)
    since = datetime(s.year, s.month, s.day, tzinfo=timezone.utc).timestamp()
    rep["failed_sources"] = store.failures_since(conn, since)
    rep["missing"] = sorted({t["name"] for t in rep["trench"] if t["value"] is None}
                            | {f"{c} DEX volume" for c, v in rep["chains"].items() if v["value"] is None}
                            | {f"{c} stablecoins" for c, v in rep["stable"].items() if v["value"] is None}
                            | {f"{p} price" for p, v in rep["price"].items() if v["value"] is None})
    return rep


# ---- text ------------------------------------------------------------------------------------------
def _chain_rows(rep) -> list[tuple[str, dict]]:
    return sorted(rep["chains"].items(), key=lambda kv: -(kv[1]["value"] or -1))


def _missing_line(rep) -> list[str]:
    items = rep["failed_sources"] + [f"no data for {m}" for m in rep["missing"]]
    return ["", "⚠️ Missing data: " + "; ".join(items)] if items else []


def _manual_lines(rep) -> list[str]:
    if not rep["manual"]:
        return []
    out = ["", "Manual metrics"]
    for m in rep["manual"]:
        note = f" ({m['source_note']})" if m["source_note"] else ""
        out.append(f"• {m['metric']}: {m['value']:g} on {m['date_utc']}{note}")
    return out


def text_daily(rep) -> str:
    d = date.fromisoformat(rep["start"])
    emoji, head = rep["headline"]
    lines = [f"📊 Market Conditions: {day_label(d)}", f"{emoji} {head}", "", "Trenches (yesterday vs 7-day avg)"]
    for t in rep["trench"]:
        lines.append(f"• {t['name']}: {usd(t['value'])} {chg(t['chg_avg'])} ({t['label'] or 'n/a'})")
    st, sol, btc = rep["stable"].get("Solana", {}), rep["price"].get("SOL", {}), rep["price"].get("BTC", {})
    lines += ["", "Liquidity",
              f"• Solana stablecoins: {usd(st.get('value'))} {chg(st.get('chg_prev'))} d/d "
              f"({st.get('label') or 'n/a'} vs 7-day avg)",
              f"• SOL: {usd(sol.get('value'))} {chg(sol.get('chg_prev'))} d/d | BTC: {usd(btc.get('value'))} "
              f"{chg(btc.get('chg_prev'))} d/d",
              "", "Chains (yesterday's DEX volume, change vs 7-day avg)"]
    for i, (c, v) in enumerate(_chain_rows(rep), 1):
        lines.append(f"{i}. {c} {usd(v['value'])} {chg(v['chg_avg'])}")
    return "\n".join(lines + _missing_line(rep))


def _period_text(rep, kind: str) -> str:
    unit = calc.UNIT[kind]
    s, e = date.fromisoformat(rep["start"]), date.fromisoformat(rep["end"])
    emoji, head = rep["headline"]
    title = f"week {range_label(s, e)}" if kind == "weekly" else month_label(s)
    avg_n = calc.AVG_N[kind]
    hl_n = calc.HIGHLOW_N[kind]
    lines = [f"📊 Market Conditions: {title}", f"{emoji} {head}", "",
             f"Trenches ({unit} total · vs last {unit} · vs {avg_n}-{unit} avg)"]
    for t in rep["trench"]:
        lines.append(f"• {t['name']}: {usd(t['value'])} · {chg(t['chg_prev'])} · {chg(t['chg_avg'])} "
                     f"({t['label'] or 'n/a'})")
        extra = [streak_text(t["streak"], unit)]
        if t.get("pct_from_high") is not None:
            below = -t["pct_from_high"]
            extra.append(f"{below:.1f}% below the {hl_n}-{unit} high" if below > 0 else f"at the {hl_n}-{unit} high")
        lines.append("   " + " · ".join(extra))
        if kind == "monthly" and t.get("high") is not None:
            lines.append(f"   12-month high {usd(t['high'])} ({month_label(date.fromisoformat(t['high_start']))})"
                         f" · low {usd(t['low'])} ({month_label(date.fromisoformat(t['low_start']))})")
    rows = _chain_rows(rep)
    moves = [(c, v["share_chg"]) for c, v in rows if v.get("share_chg") is not None]
    gain = max(moves, key=lambda x: x[1]) if moves else None
    loss = min(moves, key=lambda x: x[1]) if moves else None
    lines += ["", f"Chains ({unit} DEX volume · share · share change)"]
    for i, (c, v) in enumerate(rows, 1):
        mark = ""
        if gain and c == gain[0] and gain[1] > 0:
            mark = "  ⬆ biggest gain"
        elif loss and c == loss[0] and loss[1] < 0:
            mark = "  ⬇ biggest loss"
        share = f"{v['share']:.1f}%" if v.get("share") is not None else "n/a"
        lines.append(f"{i}. {c} {usd(v['value'])} · {share} · {pts(v.get('share_chg'))}{mark}")
    if kind == "monthly" and rep.get("share_trend"):
        months = [month_label(date.fromisoformat(m)).split()[0] for m in rep["share_trend"]["months"]]
        lines += ["", f"Chain share, last 6 months ({' → '.join(months)})"]
        for c, _ in rows:
            vals = rep["share_trend"]["chains"][c]
            lines.append(f"• {c}: " + " → ".join(f"{x:.1f}" if x is not None else "n/a" for x in vals) + "%")
    lines += ["", f"Stablecoins (change over the {unit})"]
    for c, v in sorted(rep["stable"].items(), key=lambda kv: -(kv[1]["value"] or -1)):
        lines.append(f"• {c}: {usd(v['value'])} {chg(v['chg_prev'])}")
    sol, btc = rep["price"].get("SOL", {}), rep["price"].get("BTC", {})
    lines += ["", f"Prices ({unit}ly change)", f"• SOL {usd(sol.get('value'))} {chg(sol.get('chg_prev'))} | "
              f"BTC {usd(btc.get('value'))} {chg(btc.get('chg_prev'))}"]
    lines += _manual_lines(rep)
    closing = closing_sentence(rep, unit, gain, loss)
    if closing:
        lines += ["", closing]
    return "\n".join(lines + _missing_line(rep))


def closing_sentence(rep, unit: str, gain, loss) -> str:
    """One sentence that only restates numbers already in the report."""
    parts = []
    pf = rep["trench"][0]
    if pf["streak"]:
        verb = "rose" if pf["streak"] > 0 else "fell"
        n = abs(pf["streak"])
        parts.append(f"Pump.fun bonding-curve volume {verb} " +
                     (f"this {unit}" if n == 1 else f"for a {ordinal(n)} {unit} in a row"))
    if loss and gain and loss[1] < 0 < gain[1]:
        parts.append(f"{loss[0]}'s share of DEX volume dropped {abs(loss[1]):.1f} points while "
                     f"{gain[0]}'s rose {gain[1]:.1f}")
    return ("; ".join(parts) + ".") if parts else ""


def render(rep) -> str:
    return text_daily(rep) if rep["period_type"] == "daily" else _period_text(rep, rep["period_type"])


def to_html(text: str) -> str:
    """Telegram HTML: everything escaped, title and headline in bold."""
    lines = [html.escape(x, quote=False) for x in text.split("\n")]
    for i in (0, 1):
        if i < len(lines) and lines[i]:
            lines[i] = f"<b>{lines[i]}</b>"
    return "\n".join(lines)


def generate(conn, cfg: dict, kind: str, start: date) -> dict:
    """Compute, render and store (replacing an unsent report for the same period). Returns the row."""
    rep = compute(conn, cfg, kind, start)
    text = render(rep)
    now = time.time()
    conn.execute(
        "INSERT INTO mc_reports (period_type, period_start_utc, period_end_utc, generated_at_utc, summary_text, "
        "report_json, telegram_sent) VALUES (?,?,?,?,?,?,0) ON CONFLICT(period_type, period_start_utc) DO UPDATE SET "
        "generated_at_utc=excluded.generated_at_utc, summary_text=excluded.summary_text, "
        "report_json=excluded.report_json WHERE mc_reports.telegram_sent=0",
        (kind, rep["start"], rep["end"], now, text, json.dumps(rep)))
    conn.commit()
    row = conn.execute("SELECT id, summary_text, telegram_sent FROM mc_reports WHERE period_type=? AND "
                       "period_start_utc=?", (kind, rep["start"])).fetchone()
    return {"id": row[0], "text": row[1], "sent": bool(row[2]), "report": rep}
