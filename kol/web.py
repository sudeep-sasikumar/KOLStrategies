"""Dashboard (aiohttp): one page with a tab per strategy, JSON API, password login.

Served under /kol/ on the VPS (Traefik strips the prefix), so the page uses relative links only.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import re
import secrets
import time
from pathlib import Path

from aiohttp import web

from . import analysis, db
from . import config as C
from .strategies import BY_KEY, STRATEGIES
from .strategies.base import features, in_stage

log = logging.getLogger("kol.web")
STATIC = Path(__file__).parent / "static"
COOKIE = "kol_session"
SESSION_DAYS = 14
LOCAL = ("127.0.0.1", "localhost", "::1")
MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


def _secret(data_dir: Path) -> bytes:
    p = data_dir / "dashboard.secret"
    if not p.exists():
        p.write_bytes(secrets.token_bytes(32))
    return p.read_bytes()


def make_token(secret: bytes, days: float = SESSION_DAYS) -> str:
    exp = str(int(time.time() + days * 86400))
    return f"{exp}.{hmac.new(secret, exp.encode(), hashlib.sha256).hexdigest()}"


def valid_token(secret: bytes, token: str | None) -> bool:
    if not token or "." not in token:
        return False
    exp, sig = token.split(".", 1)
    good = hmac.new(secret, exp.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, good) and exp.isdigit() and int(exp) > time.time()


def strategy_info(s) -> dict:
    return {
        "key": s.key, "name": s.name, "author": s.author, "source_url": s.source_url, "platform": s.platform,
        "summary": s.summary, "notes": list(s.notes),
        "columns": [{"key": c.key, "title": c.title, "reasons": list(c.reasons),
                     "filters": [{"key": f.key, "label": f.label, "rule": f.describe(), "quality": f.quality,
                                  "note": f.note} for f in c.filters]} for c in s.columns],
    }


def board(coll, strat) -> dict:
    now = time.time()
    out = {}
    for col in strat.columns:
        mints = set(coll.passing.get((strat.key, col.key), ()))
        if col.key == "new":       # New passes for one minute only: show the last 10 minutes of hits
            mints |= {m for m, hs in coll.hits_by_mint.items()
                      if any(h.strategy == strat.key and h.col == "new" and now - h.hit_at < 600 for h in hs)}
        rows = []
        for m in mints:
            t = coll.tokens.get(m)
            if t is None or (col.key != "new" and not in_stage(col, t, now)):
                continue
            hit = next((h for h in coll.hits_by_mint.get(m, ()) if h.strategy == strat.key and h.col == col.key),
                       None)
            f = features(t, now, coll.sol_usd)
            rows.append({
                "mint": m, "name": t.name, "symbol": t.symbol, "age_min": f["age_min"], "mc_usd": t.mc_usd,
                "vol_usd": t.vol_usd, "holders": t.holders, "dev_pct": t.dev_pct, "snipers_pct": t.snipers_pct,
                "fees_sol": t.fees_sol, "progress_pct": t.progress_pct, "socials": t.has_socials,
                "hit_at": hit.hit_at if hit else None, "mc_at_hit": hit.mc_at_hit if hit else None,
                "peak_mc": hit.peak_mc if hit else None, "migrated_at": t.migrated_at,
            })
        rows.sort(key=lambda r: -(r["hit_at"] or 0))
        out[col.key] = rows[:60]
    return out


def build_app(coll, settings: C.Settings, need_login: bool) -> web.Application:
    secret = _secret(settings.data_dir)
    fails: list[float] = []
    cache: dict = {}

    @web.middleware
    async def guard(request: web.Request, handler):
        open_paths = ("/", "/login", "/healthz", "/static/app.css", "/static/app.js", "/static/favicon.svg")
        if need_login and request.path not in open_paths and not valid_token(secret, request.cookies.get(COOKIE)):
            return web.json_response({"error": "login required"}, status=401)
        if request.method == "POST":
            origin = request.headers.get("Origin")
            if origin and origin.split("://", 1)[-1] != request.headers.get("Host", ""):
                return web.json_response({"error": "cross-origin request refused"}, status=403)
        resp = await handler(request)
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = CSP
        return resp

    def ro_conn():
        return db.connect(settings.db_path, readonly=True)

    async def index(_r):
        return web.FileResponse(STATIC / "index.html")

    async def login(request: web.Request):
        now = time.time()
        fails[:] = [t for t in fails if now - t < 900]
        if len(fails) >= 10:
            return web.json_response({"error": "too many attempts - wait 15 minutes"}, status=429)
        try:
            given = str((await request.json()).get("password", ""))
        except Exception:  # noqa: BLE001
            given = ""
        if not (settings.password and hmac.compare_digest(given.encode(), settings.password.encode())):
            fails.append(now)
            return web.json_response({"error": "wrong password"}, status=401)
        resp = web.json_response({"ok": True})
        resp.set_cookie(COOKIE, make_token(secret), max_age=SESSION_DAYS * 86400, httponly=True,
                        samesite="Strict", secure=settings.cookie_secure)
        return resp

    async def status(_r):
        st = coll.status()
        size = sum(p.stat().st_size for p in settings.data_dir.glob("kol.sqlite*"))
        st["db_mb"] = size / 1e6
        st["need_login"] = need_login
        return web.json_response(st)

    async def strategies(_r):
        return web.json_response([strategy_info(s) for s in STRATEGIES])

    async def board_h(request: web.Request):
        s = BY_KEY.get(request.match_info["key"])
        if not s:
            raise web.HTTPNotFound()
        return web.json_response({"now": time.time(), "sol_usd": coll.sol_usd, "columns": board(coll, s)})

    async def report(request: web.Request):
        s = BY_KEY.get(request.match_info["key"])
        if not s:
            raise web.HTTPNotFound()
        try:
            days = max(0.04, min(90.0, float(request.query.get("days", "7"))))
        except ValueError:
            days = 7.0
        ck = (s.key, days)
        hit = cache.get(ck)
        if hit and time.time() - hit[0] < 60:
            return web.json_response(hit[1])

        def run():
            conn = ro_conn()
            try:
                return analysis.strategy_report(conn, s, days)
            finally:
                conn.close()
        data = await asyncio.to_thread(run)
        cache[ck] = (time.time(), data)
        return web.json_response(data)

    async def token(request: web.Request):
        mint = request.match_info["mint"]
        if not MINT_RE.match(mint):
            raise web.HTTPBadRequest()

        def run():
            conn = ro_conn()
            try:
                return analysis.token_detail(conn, mint)
            finally:
                conn.close()
        data = await asyncio.to_thread(run)
        if data is None:
            raise web.HTTPNotFound()
        return web.json_response(data)

    async def healthz(_r):
        return web.json_response({"ok": True, "ws": coll.pp.connected})

    app = web.Application(middlewares=[guard])
    app.add_routes([
        web.get("/", index), web.post("/login", login), web.get("/healthz", healthz),
        web.get("/api/status", status), web.get("/api/strategies", strategies),
        web.get("/api/board/{key}", board_h), web.get("/api/report/{key}", report),
        web.get("/api/token/{mint}", token),
        web.static("/static", STATIC),
    ])
    return app


async def serve(coll, settings: C.Settings) -> None:
    need_login = settings.bind not in LOCAL
    if need_login and not settings.password:
        coll.event("warn", "dashboard is OFF: set DASHBOARD_PASSWORD to open it beyond localhost")
        return
    runner = web.AppRunner(build_app(coll, settings, need_login), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, settings.bind, settings.port).start()
    log.info("dashboard on http://%s:%d (login %s)", settings.bind, settings.port,
             "required" if need_login else "not needed")
