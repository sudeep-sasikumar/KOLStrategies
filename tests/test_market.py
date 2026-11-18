import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from kol import db
from kol.market import calc, fetch, reports, scheduler, settings, store

ROOT = Path(__file__).resolve().parent.parent


def test_periods_and_completed_only():
    assert calc.period_of("weekly", date(2026, 11, 18)) == (date(2026, 11, 16), date(2026, 11, 22))
    assert calc.period_of("monthly", date(2026, 2, 10)) == (date(2026, 2, 1), date(2026, 2, 28))
    today = date(2026, 11, 18)                                   # a Wednesday
    assert calc.last_completed("daily", today) == date(2026, 11, 17)
    assert calc.last_completed("weekly", today) == date(2026, 11, 9)
    assert calc.last_completed("weekly", date(2026, 11, 16)) == date(2026, 11, 9)   # Monday: last week done
    assert calc.last_completed("monthly", today) == date(2026, 10, 1)
    assert calc.last_completed("monthly", date(2026, 12, 1)) == date(2026, 11, 1)
    assert calc.shift("monthly", date(2026, 1, 1), -2) == date(2025, 11, 1)


def test_flow_needs_every_day_and_stock_uses_last_day():
    s = {date(2026, 11, 9) + timedelta(days=i): 10.0 for i in range(7)}
    assert calc.value(s, "dex_volume_usd", "weekly", date(2026, 11, 9)) == 70
    del s[date(2026, 11, 12)]
    assert calc.value(s, "dex_volume_usd", "weekly", date(2026, 11, 9)) is None     # never a partial sum
    assert calc.value({date(2026, 11, 15): 5.0}, "price_usd", "weekly", date(2026, 11, 9)) == 5.0


def test_labels_streak_headline():
    assert calc.label(10.1, 10) == "Rising" and calc.label(-10.1, 10) == "Falling" and calc.label(10, 10) == "Flat"
    s = {date(2026, 11, 1) + timedelta(days=i): v for i, v in enumerate([5, 4, 3, 2, 1])}
    assert calc.streak(s, "price_usd", "daily", date(2026, 11, 5)) == -4
    H = calc.headline
    assert H(["Rising"] * 3)[1] == "Trenches heating up"
    assert H(["Rising", "Rising", "Flat"])[1] == "Trenches improving"
    assert H(["Falling", "Falling", "Flat"])[1] == "Trenches cooling"
    assert H(["Falling"] * 3)[1] == "Trenches cold"
    assert H(["Rising", "Falling", "Flat"])[1] == "Mixed"
    assert H(["Rising", "Rising", None])[1] == "Mixed"           # missing data: no direction claimed


def test_parsers_and_partial_day():
    j = {"totalDataChart": [[1794787200, 1.0], [1794873600, 2.0], [1794960000, 3.0]]}  # 16, 17, 18 Nov 2026
    rows = fetch.parse_volume_chart(j, "dex_volume_usd", "Solana", "A")
    kept = fetch.keep(rows, date(2026, 11, 18), None)
    assert [r[0] for r in kept] == ["2026-11-16", "2026-11-17"]   # the current UTC day is never stored
    pj = {"coins": {"coingecko:solana": {"prices": [{"timestamp": 1794960003, "price": 72.5}]}}}
    assert fetch.parse_price_chart(pj, "coingecko:solana", "SOL")[0][:4] == (date(2026, 11, 17), "price_usd", "SOL", 72.5)


def test_report_text_is_deterministic_and_from_data(tmp_path):
    conn = db.connect(tmp_path / "t.sqlite")
    store.init(conn)
    cfg = settings.load()
    start = date(2026, 9, 1)
    rows = []
    for i in range(80):
        d = (start + timedelta(days=i)).isoformat()
        for c in cfg["dex_chains"]:
            rows.append((d, "dex_volume_usd", c, 1e8 + i * 1e6, "A"))
        for e in cfg["launchpads"]:
            rows.append((d, "launchpad_volume_usd", e, 5e7 + i * 2e6, "B"))
        for c in cfg["stablecoin_chains"]:
            rows.append((d, "stablecoin_supply_usd", c, 1e10, "D"))
        rows += [(d, "price_usd", "SOL", 100.0, "F"), (d, "price_usd", "BTC", 60000.0, "F")]
    store.upsert_metrics(conn, rows)
    conn.commit()
    for kind, s in (("daily", date(2026, 11, 18)), ("weekly", date(2026, 11, 9)), ("monthly", date(2026, 10, 1))):
        a = reports.render(reports.compute(conn, cfg, kind, s))
        b = reports.render(reports.compute(conn, cfg, kind, s))
        assert a == b
    daily = reports.generate(conn, cfg, "daily", date(2026, 11, 18))["text"]
    # 18 Nov is day 78 of the series: 5e7 + 78 * 2e6 = $206M, about +4% vs its 7-day average -> Flat
    assert "Pump.fun bonding curve: $206M ▲ 4.0% (Flat)" in daily
    weekly = reports.generate(conn, cfg, "weekly", date(2026, 11, 9))["text"]
    assert "up 9 weeks in a row" in weekly          # first full week starts 7 Sep: 9 rises up to 9 Nov
    assert conn.execute("SELECT COUNT(*) FROM mc_reports").fetchone()[0] == 2


def test_send_schedule_london():
    cfg = settings.load()
    L = scheduler.LONDON
    assert scheduler.scheduled_send("daily", cfg, datetime(2026, 11, 18, 7, 59, tzinfo=L)) is None
    assert scheduler.scheduled_send("daily", cfg, datetime(2026, 11, 18, 8, 0, tzinfo=L)) is not None
    assert scheduler.scheduled_send("weekly", cfg, datetime(2026, 11, 16, 8, 31, tzinfo=L)) is not None   # Monday
    assert scheduler.scheduled_send("weekly", cfg, datetime(2026, 11, 17, 9, 0, tzinfo=L)) is None
    assert scheduler.scheduled_send("monthly", cfg, datetime(2026, 12, 1, 9, 0, tzinfo=L)) is not None
    # summer time: 08:00 London = 07:00 UTC
    t = scheduler.scheduled_send("daily", cfg, datetime(2026, 7, 1, 7, 5, tzinfo=timezone.utc).astimezone(L))
    assert t is not None and t.astimezone(timezone.utc).hour == 7


def test_strategy_code_never_reads_market_data():
    """Information only: no strategy / collector code imports kol.market or touches mc_* tables."""
    tables = "|".join(re.findall(r"CREATE TABLE IF NOT EXISTS (mc_\w+)", store.SCHEMA))
    assert len(tables.split("|")) == 7
    pattern = re.compile(rf"\b({tables})\b|kol\.market|from \.market|from \.\.market|import market")
    allowed = {ROOT / "kol" / "__main__.py", ROOT / "kol" / "web.py"}     # start-up and route registration only
    offenders = []
    for p in (ROOT / "kol").rglob("*.py"):
        if "market" in p.parts or p in allowed:
            continue
        if pattern.search(p.read_text(encoding="utf-8")):
            offenders.append(str(p))
    assert offenders == []
