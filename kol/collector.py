"""The collector: follows every new pump.fun token for 24 hours and evaluates every strategy on it.

- PumpPortal (websocket): creations and migrations, the moment they happen.
- DexScreener: market cap, volume, buys/sells - every 20 s in a token's first 20 minutes, then less
  often (every minute while hot, every 10 minutes while above $7K) up to 24 h.
- Solana RPC: holders, dev %, snipers %, transaction count and fees - only for tokens a column is
  interested in (its cheap filters pass) or that reach $10K early.

Every column evaluation is recorded: hits (passed) with their outcome after 5 m / 1 h / 6 h / 24 h
and peak, and for every other token the closest it came (which filters failed). Signals are off.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict, deque

import aiohttp

from . import config as C
from . import db
from .models import Hit, Token
from .sources import solana
from .sources.dexscreener import BATCH, DexScreener, summarize
from .sources.metadata import fetch_socials
from .sources.prices import fetch_sol_usd
from .sources.pumpportal import PumpPortal
from .sources.solana import RPCError, SolanaRPC
from .strategies import STRATEGIES
from .strategies.base import evaluate, features, in_stage
from .util import progress_from_mc_sol

log = logging.getLogger("kol.collector")

AUDIT_PRIO = {"soon": 0, "migrated": 1, "new": 2, "early": 3}
MAX_SIG_PAGES = 15
MAX_FEE_SAMPLES = 30
AUDIT_QUEUE_MAX = 600


class Collector:
    def __init__(self, settings: C.Settings, conn, session: aiohttp.ClientSession):
        self.s = settings
        self.conn = conn
        self.session = session
        self.tokens: dict[str, Token] = {}
        self.dirty: set[str] = set()
        self.hits_by_mint: dict[str, list[Hit]] = defaultdict(list)
        self.hit_keys: set[tuple] = set()
        self.dirty_hits: list[Hit] = []
        self.best_eval: dict[tuple, int] = {}
        self.pending_evals: list[tuple] = []
        self.passing: dict[tuple, set[str]] = defaultdict(set)
        self.early_sigs: dict[str, list[dict]] = {}
        self.audit_q: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.audit_pending: set[str] = set()
        self.meta_q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self.meta_pending: set[str] = set()
        self.sol_usd: float | None = None
        self.sol_usd_at: float | None = None
        self.started = time.time()
        self.counts = defaultdict(int)
        self.last_create_at: float | None = None
        self.last_migration_at: float | None = None
        self.ws_up_since: float | None = None
        self.coverage: dict[int, list] = {}
        self.events: deque = deque(maxlen=200)
        self.dex = DexScreener(session)
        self.rpc = SolanaRPC(session, settings.rpc_url, settings.rpc_rps, settings.public_rpc)
        self.pp = PumpPortal(session, settings.pumpportal_ws, self.on_create, self.on_migrate, self.on_ws_status)
        self._seq = 0

    # ---- start-up ---------------------------------------------------------------------------
    def load(self) -> None:
        for t in db.load_active(self.conn):
            self.tokens[t.mint] = t
        for h in db.load_open_hits(self.conn, time.time() - C.TRACK_S - 3600):
            self.hits_by_mint[h.mint].append(h)
            self.hit_keys.add((h.strategy, h.col, h.mint))
        self.sol_usd = db.get_state(self.conn, "sol_usd")
        self.event("info", f"started (version {self.s.version}); {len(self.tokens)} tokens still being followed")

    def event(self, level: str, msg: str) -> None:
        ts = time.time()
        self.events.appendleft({"ts": ts, "level": level, "msg": msg})
        try:
            db.log_event(self.conn, ts, level, msg)
        except Exception:  # noqa: BLE001
            pass
        (log.warning if level != "info" else log.info)(msg)

    # ---- PumpPortal events --------------------------------------------------------------------
    def on_ws_status(self, up: bool, why: str) -> None:
        now = time.time()
        if up:
            self.ws_up_since = now
            self.event("info", "PumpPortal stream connected")
        else:
            self._add_uptime(now)
            self.ws_up_since = None
            self.event("warn", "PumpPortal stream disconnected - reconnecting")

    def _add_uptime(self, now: float) -> None:
        if self.ws_up_since is None:
            return
        start = self.ws_up_since
        while start < now:
            hour = int(start // 3600)
            end = min(now, (hour + 1) * 3600)
            self.coverage.setdefault(hour, [0, 0.0])[1] += end - start
            start = end
        self.ws_up_since = now

    async def on_create(self, d: dict) -> None:
        now = time.time()
        mint = d["mint"]
        t = self.tokens.get(mint) or Token(mint=mint, first_seen=now)
        t.name = str(d.get("name") or "")[:80]
        t.symbol = str(d.get("symbol") or "")[:30]
        t.uri = str(d.get("uri") or "")[:300]
        t.dev = d.get("traderPublicKey") or ""
        t.bonding_curve = d.get("bondingCurveKey") or ""
        t.pool = d.get("pool") or ""
        t.created_at = t.created_at or now
        t.seen_create = 1
        if "is_mayhem_mode" in d:
            t.mayhem = int(bool(d.get("is_mayhem_mode")))
        t.initial_buy = _f(d.get("initialBuy"))
        t.dev_initial_pct = t.initial_buy / 1e9 * 100 if t.initial_buy is not None else None
        t.mc_sol_create = _f(d.get("marketCapSol"))
        t.progress_pct = progress_from_mc_sol(t.mc_sol_create)
        if self.sol_usd and t.mc_sol_create:
            t.mc_usd = t.mc_sol_create * self.sol_usd
            t.vol_usd = (_f(d.get("solAmount")) or 0) * self.sol_usd
            self._observe(t, t.mc_usd, now)
        t.next_poll = now + 15                     # DexScreener needs a few seconds to index it
        if not t.mayhem and t.uri:
            self._queue_meta(t)                    # socials, needed at creation by some New columns
        self.tokens[mint] = t
        self.dirty.add(mint)
        self.counts["creates"] += 1
        self.last_create_at = now
        self.coverage.setdefault(int(now // 3600), [0, 0.0])[0] += 1
        self._evaluate(t, now)

    async def on_migrate(self, d: dict) -> None:
        now = time.time()
        mint = d["mint"]
        t = self.tokens.get(mint)
        if t is None:
            row = self.conn.execute("SELECT * FROM tokens WHERE mint=?", (mint,)).fetchone()
            t = Token(**{k: row[k] for k in row.keys()}) if row else Token(mint=mint, first_seen=now)
        t.migrated_at = now
        t.done = 0
        t.next_poll = now + 30
        self.tokens[mint] = t
        self.dirty.add(mint)
        self.counts["migrations"] += 1
        self.last_migration_at = now

    # ---- market data polling ------------------------------------------------------------------
    async def poll_loop(self) -> None:
        while True:
            now = time.time()
            due = [t for t in self.tokens.values() if not t.done and t.next_poll <= now]
            due.sort(key=lambda t: t.next_poll)
            due = due[:BATCH * 12]
            for t in due:
                t.next_poll = now + 120                # in flight: not picked again meanwhile
            batches = [due[i:i + BATCH] for i in range(0, len(due), BATCH)]
            if batches:
                await asyncio.gather(*(self._poll_batch(b) for b in batches))
            else:
                await asyncio.sleep(1)

    async def _poll_batch(self, toks: list[Token]) -> None:
        res = await self.dex.tokens([t.mint for t in toks])
        now = time.time()
        for t in toks:
            if res is None:
                t.next_poll = now + 30
                continue
            pairs = res.get(t.mint)
            self._apply_market(t, summarize(pairs) if pairs else None, now)

    def _apply_market(self, t: Token, m: dict | None, now: float) -> None:
        if m is None:
            t.dex_misses += 1
            if t.dex_misses >= 3:                  # not indexed: count it as dead at its last known value
                self._observe(t, t.mc_usd, now, fill_only=True)
        else:
            t.dex_misses = 0
            if m["mc"]:
                t.mc_usd = float(m["mc"])
            t.liq_usd = m["liq"]
            t.pair, t.dex_id = m["pair"], m["dex_id"]
            if not t.name and not t.symbol:        # first seen at migration: no creation event
                t.name, t.symbol = m.get("name", ""), m.get("symbol", "")
            if m["has_bc"]:
                t.vol_bc_usd = m["vol_bc"]
            if m["has_amm"]:
                t.amm_txns = m["amm_txns"]
                if t.migrated_at is None and m["dex_id"] == "pumpswap" and t.seen_create:
                    t.migrated_at = now            # migration event missed (stream gap)
            t.vol_usd = (t.vol_bc_usd or 0) + (m["vol_amm"] or 0)
            t.buys, t.sells = m["buys"], m["sells"]
            if t.migrated_at is None and self.sol_usd and t.mc_usd:
                t.progress_pct = progress_from_mc_sol(t.mc_usd / self.sol_usd)
            elif t.migrated_at is not None:
                t.progress_pct = 100.0
            if not t.has_socials and (m["twitter"] or m["telegram"] or m["website"]):
                t.twitter, t.telegram, t.website = m["twitter"], m["telegram"], m["website"]
            self._recompute_fees(t)
            self._observe(t, t.mc_usd, now)
        t.last_update = now
        t.next_poll = self._schedule(t, now)
        self.dirty.add(t.mint)
        self._evaluate(t, now)

    def _observe(self, t: Token, mc: float | None, now: float, fill_only: bool = False) -> None:
        """Peak and checkpoint values for the token and for each of its hits."""
        if mc is None:
            return
        if not fill_only and (t.peak_mc is None or mc > t.peak_mc):
            t.peak_mc, t.peak_at = mc, now
        for label, sec in C.CHECKPOINTS:
            if getattr(t, f"mc_{label}") is None and now >= t.born + sec:
                setattr(t, f"mc_{label}", mc)
        for h in self.hits_by_mint.get(t.mint, ()):
            changed = False
            if not fill_only and now - h.hit_at <= C.TRACK_S and (h.peak_mc is None or mc > h.peak_mc):
                h.peak_mc, h.peak_at = mc, now
                changed = True
            for label, sec in C.HIT_CHECKPOINTS:
                if getattr(h, f"mc_{label}") is None and now >= h.hit_at + sec:
                    setattr(h, f"mc_{label}", mc)
                    changed = True
            mig = int(t.migrated_at is not None)
            if mig != h.migrated:
                h.migrated, changed = mig, True
            if changed:
                self.dirty_hits.append(h)

    def _schedule(self, t: Token, now: float) -> float:
        cands = []
        age = now - t.born
        if age < C.LIVE_WINDOW_S:
            cands.append(now + C.LIVE_POLL_S)
        if t.migrated_at is not None:
            mig_age = now - t.migrated_at
            if mig_age < 3600:
                cands.append(now + 60)
            elif mig_age < C.TRACK_S:
                cands.append(now + 300)
        hits = [h for h in self.hits_by_mint.get(t.mint, ()) if now - h.hit_at < C.TRACK_S + 900]
        if age < C.TRACK_S:
            mc = t.mc_usd or 0
            if mc >= C.HOT_MC_USD or (mc >= C.WARM_MC_USD and any(now - h.hit_at < 3600 for h in hits)):
                cands.append(now + C.HOT_POLL_S)
            elif mc >= C.WARM_MC_USD:
                cands.append(now + C.WARM_POLL_S)
        for label, sec in C.CHECKPOINTS:
            if getattr(t, f"mc_{label}") is None:
                cands.append(max(now + 30, t.born + sec))
        for h in hits:
            for label, sec in C.HIT_CHECKPOINTS:
                if getattr(h, f"mc_{label}") is None:
                    cands.append(max(now + 30, h.hit_at + sec))
        if not cands:
            t.done = 1
            return 0.0
        return min(cands)

    # ---- strategy evaluation ------------------------------------------------------------------
    def _evaluate(self, t: Token, now: float) -> None:
        feats = features(t, now, self.sol_usd)
        want_audit: str | None = None
        want_meta = False
        for strat in STRATEGIES:
            for col in strat.columns:
                key = (strat.key, col.key)
                if not in_stage(col, t, now):
                    self.passing[key].discard(t.mint)
                    continue
                r = evaluate(col, feats)
                if r.passed:
                    self.passing[key].add(t.mint)
                    if (strat.key, col.key, t.mint) not in self.hit_keys:
                        self._new_hit(strat.key, col.key, t, feats, now)
                else:
                    self.passing[key].discard(t.mint)
                n = len(r.failed) + len(r.unknown)
                ek = (strat.key, col.key, t.mint)
                if ek not in self.best_eval or n < self.best_eval[ek]:
                    self.best_eval[ek] = n
                    self.pending_evals.append((strat.key, col.key, t.mint, now, n,
                                               json.dumps(r.failed + [k + "?" for k in r.unknown])))
                if r.cheap_ok:
                    want_meta = True
                    audit_keys = {f.key for f in col.filters if f.audit}
                    if (set(r.unknown) | set(r.failed)) & audit_keys:
                        stale = t.audited_at is None or now - t.audited_at >= col.audit_refresh_s
                        if stale and t.audits < col.audit_max:
                            if want_audit is None or AUDIT_PRIO.get(col.key, 2) < AUDIT_PRIO.get(want_audit, 2):
                                want_audit = col.key
        if (want_audit is None and not t.audits and t.migrated_at is None
                and (t.mc_usd or 0) >= C.AUDIT_MC_USD and now - t.born <= C.AUDIT_EARLY_S):
            want_audit = "early"                   # for the pattern study: on-chain profile of early movers
        if want_audit:
            self._queue_audit(t, want_audit)
        if (want_meta or (t.mc_usd or 0) >= C.AUDIT_MC_USD) and not t.socials_checked and t.uri:
            self._queue_meta(t)

    def _new_hit(self, strat: str, col: str, t: Token, feats: dict, now: float) -> None:
        snap = {k: v for k, v in feats.items() if k != "text"}
        snap.update(name=t.name, symbol=t.symbol, hour_utc=time.gmtime(now).tm_hour)
        h = Hit(strategy=strat, col=col, mint=t.mint, hit_at=now, mc_at_hit=t.mc_usd,
                snapshot=json.dumps(snap), peak_mc=t.mc_usd, peak_at=now,
                migrated=int(t.migrated_at is not None))
        self.hits_by_mint[t.mint].append(h)
        self.hit_keys.add((strat, col, t.mint))
        self.dirty_hits.append(h)
        self.counts[f"hits_{strat}_{col}"] += 1
        t.next_poll = min(t.next_poll or now + 60, now + 60)

    # ---- on-chain audit -----------------------------------------------------------------------
    def _queue_audit(self, t: Token, why: str) -> None:
        if t.mint in self.audit_pending:
            return
        if self.audit_q.qsize() >= AUDIT_QUEUE_MAX and AUDIT_PRIO.get(why, 3) >= 2:
            return                                 # busy: skip the nice-to-have look-ups
        self._seq += 1
        self.audit_pending.add(t.mint)
        self.audit_q.put_nowait((AUDIT_PRIO.get(why, 3), self._seq, t.mint))

    async def audit_worker(self) -> None:
        while True:
            _, _, mint = await self.audit_q.get()
            t = self.tokens.get(mint)
            try:
                if t is not None:
                    await self.audit(t)
                    self.counts["audits"] += 1
            except RPCError as e:
                self.counts["audit_errors"] += 1
                log.info("audit %s failed: %s", mint, e)
                if t is not None:
                    t.audited_at = time.time()
            except Exception:  # noqa: BLE001
                self.counts["audit_errors"] += 1
                log.exception("audit %s crashed", mint)
                if t is not None:
                    t.audited_at = time.time()
            finally:
                self.audit_pending.discard(mint)
            if t is not None:
                self.dirty.add(mint)
                self._evaluate(t, time.time())

    async def audit(self, t: Token) -> None:
        rpc = self.rpc
        if t.supply_raw is None:
            t.supply_raw = await rpc.supply(t.mint) or 1e15
        addr = t.bonding_curve or t.mint
        # "first 3 slots" snipers / creation-slot insiders only mean something for pump.fun bonding-curve
        # launches; for other launchpads they stay unknown rather than wrong
        pump_launch = bool(t.seen_create or t.mint.endswith("pump"))
        if pump_launch and not t.sniper_list and t.tx_complete and t.mint not in self.early_sigs:
            t.sig_newest = ""                      # restarted since the first look: fetch the first slots again
        recent = await self._update_signatures(t, addr)
        if pump_launch and not t.sniper_list and t.mint in self.early_sigs:
            await self._find_snipers(t)
        early = {s["signature"] for s in self.early_sigs.get(t.mint, ())}
        for s in recent:
            if t.fee_samples >= MAX_FEE_SAMPLES:
                break
            if s["signature"] in early:
                continue
            tx = await rpc.transaction(s["signature"])
            if tx:
                t.fee_samples += 1
                t.fee_sample_sol += solana.tx_cost_sol(tx)
        prog, accounts = await rpc.token_accounts(t.mint, t.token_program)
        t.token_program = prog or t.token_program
        exclude = {x for x in (t.bonding_curve, t.pair) if x}
        snipers = set(json.loads(t.sniper_list)) if t.sniper_list else set()
        insiders = set(json.loads(t.insider_list)) if t.insider_list else set()
        h = solana.holdings(accounts, t.supply_raw, t.dev, snipers, exclude, insiders)
        t.holders, t.dev_pct, t.top10_pct = h["holders"], h["dev_pct"], h["top10_pct"]
        t.snipers_pct = h["snipers_pct"] if t.sniper_list else None
        t.insiders_pct = h["insiders_pct"] if t.sniper_list else None
        t.audited_at = time.time()
        t.audits += 1
        self._recompute_fees(t)

    async def _update_signatures(self, t: Token, addr: str) -> list[dict]:
        rpc = self.rpc
        if not t.sig_newest:
            sigs, before, complete = [], None, False
            for _ in range(MAX_SIG_PAGES):
                page = await rpc.signatures(addr, before=before)
                sigs.extend(page)
                if len(page) < 1000:
                    complete = True
                    break
                before = page[-1]["signature"]
            t.tx_count, t.tx_complete = len(sigs), int(complete)
            if sigs:
                t.sig_newest = sigs[0]["signature"]
            if complete and sigs:
                t.create_slot = sigs[-1]["slot"]
                self.early_sigs[t.mint] = [s for s in reversed(sigs) if s["slot"] <= t.create_slot + C.SNIPER_SLOTS]
            return sigs[:C.FEE_SAMPLE_TXS]
        new, before = [], None
        for _ in range(MAX_SIG_PAGES):
            page = await rpc.signatures(addr, before=before, until=t.sig_newest)
            new.extend(page)
            if len(page) < 1000:
                break
            before = page[-1]["signature"]
        if new:
            t.tx_count = (t.tx_count or 0) + len(new)
            t.sig_newest = new[0]["signature"]
        return new[:C.FEE_SAMPLE_TXS]

    async def _find_snipers(self, t: Token) -> None:
        early = self.early_sigs.get(t.mint, [])[:C.SNIPER_TX_CAP]
        exclude = {x for x in (t.bonding_curve, t.pair, t.dev) if x}
        buyers, bundle = set(), set()
        cost, n = 0.0, 0
        for s in early:
            tx = await self.rpc.transaction(s["signature"])
            if not tx:
                continue
            n += 1
            cost += solana.tx_cost_sol(tx)
            if s.get("err") is not None:
                continue
            for owner, d in solana.token_deltas(tx, t.mint).items():
                if d > 0 and owner not in exclude:
                    buyers.add(owner)
                    if s["slot"] == t.create_slot:
                        bundle.add(owner)
        t.early_n, t.fee_early_sol = n, cost
        t.sniper_list = json.dumps(sorted(buyers))
        t.insider_list = json.dumps(sorted(bundle))
        t.snipers, t.bundle_buyers = len(buyers), len(bundle)

    def _recompute_fees(self, t: Token) -> None:
        sol = self.sol_usd
        if t.tx_count is None or not sol or (t.fee_samples == 0 and t.early_n == 0):
            return
        avg = (t.fee_sample_sol / t.fee_samples) if t.fee_samples else (t.fee_early_sol / max(t.early_n, 1))
        # signatures of the mint itself (token first seen at migration) already include the AMM trades
        later = max(0, t.tx_count - t.early_n) + ((t.amm_txns or 0) if t.bonding_curve else 0)
        t.fees_net_sol = t.fee_early_sol + later * avg
        vol_bc = t.vol_bc_usd if t.vol_bc_usd is not None else (t.vol_usd or 0)
        vol_amm = max(0.0, (t.vol_usd or 0) - vol_bc)
        t.fees_trade_sol = vol_bc / sol * C.BONDING_FEE_RATE + vol_amm / sol * C.AMM_FEE_RATE
        # Terminal-style "total fees": what traders paid to land their transactions (network + priority
        # + tips). pump.fun's own trading fee is kept apart in fees_trade_sol for the pattern study.
        t.fees_sol = t.fees_net_sol

    # ---- socials -------------------------------------------------------------------------------
    def _queue_meta(self, t: Token) -> None:
        if t.mint in self.meta_pending:
            return
        try:
            self.meta_q.put_nowait(t.mint)
            self.meta_pending.add(t.mint)
        except asyncio.QueueFull:
            pass

    async def meta_worker(self) -> None:
        while True:
            mint = await self.meta_q.get()
            t = self.tokens.get(mint)
            try:
                if t is not None and not t.socials_checked:
                    s = await fetch_socials(self.session, t.uri)
                    if s:
                        t.twitter = t.twitter or s["twitter"]
                        t.telegram = t.telegram or s["telegram"]
                        t.website = t.website or s["website"]
                        t.community = t.community or s.get("community", "")
                    t.socials_checked = 1 if s else 2
                    self.counts["meta_ok" if s else "meta_failed"] += 1
                    self.dirty.add(mint)
                    self._evaluate(t, time.time())
            except Exception:  # noqa: BLE001
                self.counts["meta_failed"] += 1
                log.exception("metadata %s failed", mint)
            finally:
                self.meta_pending.discard(mint)

    # ---- housekeeping -------------------------------------------------------------------------
    async def price_loop(self) -> None:
        while True:
            p = await fetch_sol_usd(self.session)
            if p:
                self.sol_usd, self.sol_usd_at = p, time.time()
                db.set_state(self.conn, "sol_usd", p)
            await asyncio.sleep(60)

    def flush(self) -> None:
        now = time.time()
        self._add_uptime(now)
        toks = [self.tokens[m] for m in self.dirty if m in self.tokens]
        self.dirty.clear()
        db.save_tokens(self.conn, toks)
        if self.dirty_hits:
            seen, hits = set(), []
            for h in self.dirty_hits:
                if id(h) not in seen:
                    seen.add(id(h))
                    hits.append(h)
            self.dirty_hits.clear()
            db.save_hits(self.conn, hits)
        if self.pending_evals:
            db.save_evals(self.conn, self.pending_evals)
            self.pending_evals.clear()
        for hour, (creates, up) in self.coverage.items():
            self.conn.execute("INSERT INTO coverage VALUES (?,?,?) ON CONFLICT(hour) DO UPDATE SET "
                              "creates=coverage.creates+excluded.creates, ws_up_s=coverage.ws_up_s+excluded.ws_up_s",
                              (hour, creates, up))
        self.coverage.clear()
        self.conn.commit()
        # forget finished tokens
        for m in [m for m, t in self.tokens.items() if t.done]:
            self.tokens.pop(m, None)
            self.early_sigs.pop(m, None)
            self.hits_by_mint.pop(m, None)
        cutoff = now - C.TRACK_S - 3600
        for m in [m for m, hs in self.hits_by_mint.items() if all(h.hit_at < cutoff for h in hs)]:
            self.hits_by_mint.pop(m, None)
        if len(self.best_eval) > 400_000:
            self.best_eval.clear()

    async def flush_loop(self) -> None:
        while True:
            await asyncio.sleep(5)
            try:
                self.flush()
            except Exception:  # noqa: BLE001
                log.exception("flush failed")

    # ---- status for the dashboard ------------------------------------------------------------
    def status(self) -> dict:
        now = time.time()
        live = sum(1 for t in self.tokens.values() if now - t.born < C.LIVE_WINDOW_S)
        return {
            "version": self.s.version,
            "started": self.started,
            "now": now,
            "ws_connected": self.pp.connected,
            "last_create_at": self.last_create_at,
            "last_migration_at": self.last_migration_at,
            "creates": self.counts["creates"],
            "migrations": self.counts["migrations"],
            "followed": len(self.tokens),
            "live": live,
            "sol_usd": self.sol_usd,
            "dex": {"requests": self.dex.requests, "errors": self.dex.errors, "last_error": self.dex.last_error},
            "rpc": {"public": self.s.public_rpc, "calls": self.rpc.calls, "errors": self.rpc.errors,
                    "last_error": self.rpc.last_error, "audits": self.counts["audits"],
                    "audit_errors": self.counts["audit_errors"], "queue": self.audit_q.qsize()},
            "meta": {"ok": self.counts["meta_ok"], "failed": self.counts["meta_failed"],
                     "queue": self.meta_q.qsize()},
            "events": list(self.events)[:30],
        }

    async def run(self) -> None:
        self.load()
        tasks = [self.pp.run(), self.poll_loop(), self.price_loop(), self.flush_loop()]
        tasks += [self.audit_worker() for _ in range(2)]
        tasks += [self.meta_worker() for _ in range(6)]
        await asyncio.gather(*tasks)


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
