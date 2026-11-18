import asyncio
import base64
import json
import struct
import time

import pytest

from kol import analysis, db
from kol import config as C
from kol.collector import Collector
from kol.models import Token
from kol.sources import solana
from kol.sources.dexscreener import summarize
from kol.strategies.base import evaluate, features
from kol.strategies.daumen import MIGRATED, NEW, SOON, STRATEGY
from kol.util import b58encode, progress_from_mc_sol


def test_b58():
    assert b58encode(bytes(32)) == "1" * 32
    assert b58encode(b"\x00\x01") == "12"


def test_progress_curve():
    assert progress_from_mc_sol(27.96) == pytest.approx(0, abs=0.5)
    assert progress_from_mc_sol(411) == pytest.approx(100, abs=1)
    assert 50 < progress_from_mc_sol(80) < 60


def _tok(**kw):
    base = dict(mint="M", created_at=time.time() - 30, mayhem=0, name="Cat", symbol="CAT", mc_usd=5000)
    base.update(kw)
    return Token(**base)


def test_new_column():
    now = time.time()
    assert evaluate(NEW, features(_tok(), now, 74)).passed
    r = evaluate(NEW, features(_tok(mayhem=1), now, 74))
    assert not r.passed and r.failed == ["mayhem"]
    r = evaluate(NEW, features(_tok(name="FREE ENTRY club"), now, 74))
    assert r.failed == ["keywords"]
    r = evaluate(NEW, features(_tok(created_at=now - 90), now, 74))
    assert r.failed == ["age"]
    r = evaluate(NEW, features(_tok(mc_usd=40_000), now, 74))
    assert r.failed == ["mc_max"]


def test_soon_needs_audit_then_passes():
    now = time.time()
    t = _tok(created_at=now - 300, mc_usd=8000, vol_usd=5000)
    r = evaluate(SOON, features(t, now, 74))
    assert not r.passed and r.cheap_ok and set(r.unknown) == {"dev", "snipers", "holders", "fees"}
    t.holders, t.dev_pct, t.snipers_pct, t.fees_sol = 10, 5.0, 3.0, 0.5
    assert evaluate(SOON, features(t, now, 74)).passed
    t.dev_pct = 30
    r = evaluate(SOON, features(t, now, 74))
    assert r.failed == ["dev"] and r.cheap_ok


def test_migrated_unknown_mayhem_ok():
    now = time.time()
    t = Token(mint="M", migrated_at=now, mc_usd=70_000, snipers_pct=10, fees_sol=7)
    assert evaluate(MIGRATED, features(t, now, 74)).passed
    t.fees_sol = 5
    assert evaluate(MIGRATED, features(t, now, 74)).failed == ["fees"]


def test_parse_token_accounts_and_holdings():
    owner = bytes(range(32))
    data = base64.b64encode(owner + struct.pack("<Q", 123)).decode()
    acc = solana.parse_token_accounts([{"account": {"data": [data, "base64"]}}])
    assert acc == [(b58encode(owner), 123)]
    h = solana.holdings([("dev", 100), ("a", 50), ("b", 0), ("curve", 800), ("s", 50)], 1000, "dev", {"s"}, {"curve"})
    assert h["holders"] == 3 and h["dev_pct"] == 10 and h["snipers_pct"] == 5 and h["top10_pct"] == 20


def test_tx_parsing():
    tx = {"transaction": {"message": {"accountKeys": [{"pubkey": "payer"}], "instructions": [
        {"program": "system", "parsed": {"type": "transfer", "info": {
            "destination": "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5", "lamports": 1_000_000}}}]}},
          "meta": {"fee": 5000, "innerInstructions": [],
                   "preTokenBalances": [{"accountIndex": 2, "mint": "M", "owner": "curve", "uiTokenAmount": {"amount": "1000"}}],
                   "postTokenBalances": [{"accountIndex": 2, "mint": "M", "owner": "curve", "uiTokenAmount": {"amount": "900"}},
                                         {"accountIndex": 3, "mint": "M", "owner": "buyer", "uiTokenAmount": {"amount": "100"}}]}}
    assert solana.tx_cost_sol(tx) == pytest.approx(0.001005)
    assert solana.token_deltas(tx, "M") == {"curve": -100, "buyer": 100}
    assert solana.signer(tx) == "payer"


def test_dexscreener_summary():
    pairs = [{"dexId": "pumpfun", "marketCap": 9000, "liquidity": {"usd": 0}, "volume": {"h24": 5000},
              "txns": {"h24": {"buys": 30, "sells": 10}}, "pairAddress": "P1"},
             {"dexId": "pumpswap", "marketCap": 70000, "liquidity": {"usd": 20000}, "volume": {"h24": 3000},
              "txns": {"h24": {"buys": 5, "sells": 5}}, "pairAddress": "P2",
              "info": {"socials": [{"type": "twitter", "url": "x"}]}}]
    s = summarize(pairs)
    assert s["mc"] == 70000 and s["pair"] == "P2" and s["vol_bc"] == 5000 and s["vol_amm"] == 3000
    assert s["amm_txns"] == 10 and s["buys"] == 35 and s["twitter"] == "x"


class _Sess:
    pass


def test_collector_flow_and_report(tmp_path):
    s = C.Settings(data_dir=tmp_path, bind="127.0.0.1", port=0, password="", cookie_secure=False, tg_token="",
                   tg_chat="", rpc_url=C.PUBLIC_RPC, rpc_rps=4, pumpportal_ws="", domain="", base_path="/kol",
                   version="t")
    conn = db.connect(s.db_path)
    db.init(conn)

    async def go():
        coll = Collector(s, conn, _Sess())
        coll.sol_usd = 100.0
        await coll.on_create({"mint": "Mint1", "name": "Dog", "symbol": "DOG", "traderPublicKey": "dev",
                              "bondingCurveKey": "curve", "marketCapSol": 30, "initialBuy": 1e7, "solAmount": 0.3,
                              "is_mayhem_mode": False, "pool": "pump"})
        t = coll.tokens["Mint1"]
        assert ("daumen", "new", "Mint1") in coll.hit_keys          # passes New at creation
        t.created_at -= 120                                         # 2 minutes old
        coll._apply_market(t, {"mc": 9000, "liq": 0, "pair": "P", "dex_id": "pumpfun", "has_bc": True,
                               "has_amm": False, "vol_bc": 6000, "vol_amm": 0, "amm_txns": 0, "buys": 40,
                               "sells": 10, "price_native": None, "twitter": "", "telegram": "", "website": ""},
                           time.time())
        assert coll.audit_q.qsize() == 1                            # Soon cheap filters pass -> audit
        t.holders, t.dev_pct, t.snipers_pct, t.fees_sol, t.audited_at = 12, 2.0, 4.0, 0.4, time.time()
        coll._evaluate(t, time.time())
        assert ("daumen", "soon", "Mint1") in coll.hit_keys
        coll._observe(t, 30_000, time.time())
        coll.flush()
        return coll

    coll = asyncio.run(go())
    assert conn.execute("SELECT COUNT(*) FROM hits").fetchone()[0] == 2
    rep = analysis.strategy_report(db.connect(s.db_path, readonly=True), STRATEGY, 1)
    assert rep["columns"]["soon"]["hits"] == 1
    assert rep["universe"]["created"] == 1
    hit = coll.hits_by_mint["Mint1"][1]
    assert hit.peak_mc == 30_000
    ev = json.loads(conn.execute("SELECT failed FROM evals WHERE col='soon'").fetchone()[0])
    assert ev == []


def test_old_filters_new_column_needs_a_social():
    from kol.strategies.daumen_old import NEW as OLD_NEW
    now = time.time()
    t = _tok(created_at=now - 200, mc_usd=3000)          # no age filter: 3+ minutes old is fine
    r = evaluate(OLD_NEW, features(t, now, 74))
    assert not r.passed and r.unknown == ["socials"]      # metadata not read yet
    t.socials_checked = 1
    assert evaluate(OLD_NEW, features(t, now, 74)).failed == ["socials"]
    t.community = "https://coincommunities.org/x"       # pump.fun's auto link does not count
    assert evaluate(OLD_NEW, features(t, now, 74)).failed == ["socials"]
    t.twitter = "https://x.com/abc"
    assert evaluate(OLD_NEW, features(t, now, 74)).passed
    t.mc_usd = 31_000
    assert evaluate(OLD_NEW, features(t, now, 74)).failed == ["mc_max"]


def test_old_filters_soon_insiders():
    from kol.strategies.daumen_old import SOON as OLD_SOON
    now = time.time()
    t = _tok(created_at=now - 20 * 60, mc_usd=8000, vol_usd=5000, holders=3, dev_pct=20, snipers_pct=24,
             insiders_pct=10, fees_sol=0.06)
    assert evaluate(OLD_SOON, features(t, now, 74)).passed   # 20 min old, no holders filter
    t.insiders_pct = 30
    assert evaluate(OLD_SOON, features(t, now, 74)).failed == ["insiders"]
    t.insiders_pct, t.created_at = 10, now - 25 * 60
    assert evaluate(OLD_SOON, features(t, now, 74)).failed == ["age"]


def test_insiders_holdings():
    h = solana.holdings([("dev", 100), ("i1", 200), ("s", 50)], 1000, "dev", {"s", "i1"}, set(), {"i1"})
    assert h["insiders_pct"] == 20 and h["snipers_pct"] == 25


def test_other_launchpads_are_not_evaluated():
    from kol.strategies.base import in_stage, in_universe
    now = time.time()
    bonk = _tok(pool="bonk", mint="Abc", mc_usd=3000)
    assert not in_universe(bonk) and not in_stage(NEW, bonk, now)
    assert in_universe(_tok(pool="pump", mint="Xyz"))
    assert in_universe(Token(mint="Abcpump")) and not in_universe(Token(mint="Abc123"))   # seen only at migration


def test_runner_rule(tmp_path):
    conn = db.connect(tmp_path / "r.sqlite")
    db.init(conn)
    now = time.time()
    rows = [  # mint, pool, launch mc, peak, volume -> runner?
        ("Apump", "pump", 2000, 150_000, 80_000),     # yes
        ("Bpump", "pump", 2000, 150_000, 10_000),     # no: too little volume
        ("Cpump", "pump", 60_000, 150_000, 90_000),   # no: only 2.5x its launch market cap
        ("Dbonk", "bonk", 2000, 900_000, 900_000),    # no: other launchpad
    ]
    db.save_tokens(conn, [Token(mint=m, pool=p, first_seen=now - 60, created_at=now - 60, seen_create=1,
                                mc_create_usd=mc0, peak_mc=pk, vol_usd=v) for m, p, mc0, pk, v in rows])
    conn.commit()
    rep = analysis.strategy_report(db.connect(tmp_path / "r.sqlite", readonly=True), STRATEGY, 1)
    assert rep["universe"]["created"] == 3 and rep["universe"]["other_launchpads"] == 1
    assert rep["universe"]["runners"] == 1
