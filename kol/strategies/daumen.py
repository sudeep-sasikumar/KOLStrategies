"""Daumen - "My New Filters (Updated)" (YouTube, 12 Nov 2026). See docs/strategies/daumen-filters.md."""
from __future__ import annotations

from .base import APPROX, ESTIMATE, EXACT, Column, Filter, Strategy

# One word of the second phrase is censored in the video; only the visible words are used.
KEYWORDS = ("FREE ENTRY", "READ OR")

MAYHEM = Filter("mayhem", "Mayhem mode", "mayhem", "is_false", quality=EXACT, unknown_ok=True,
                note="from the creation event; unknown for tokens created before the collector started")
KEYWORD_FILTER = Filter("keywords", "Exclude keywords", "text", "excludes_any", KEYWORDS, quality=APPROX,
                        note="name + symbol; one censored word in the video is not known")

NEW = Column(
    key="new", title="New", stage="new", horizon_s=120,
    filters=(
        MAYHEM,
        Filter("age", "Token age (mins)", "age_min", "<=", 1),
        Filter("mc_min", "Market cap ($)", "mc_usd", ">=", 1_000),
        Filter("mc_max", "Market cap ($)", "mc_usd", "<=", 30_000),
        KEYWORD_FILTER,
    ),
    reasons=(
        "Mayhem mode hidden: nobody uses it but there are many deploys on it.",
        "Token age max 1 min: older tokens sitting in the column are noise, especially during spam deploys.",
        "Market cap $1K-$30K: minimum lowered from $3K because coins can now be paired to other coins.",
        "No socials filter: in New you want to see everything.",
    ),
)

SOON = Column(
    key="soon", title="Soon", stage="bonding", horizon_s=16 * 60, audit_refresh_s=90, audit_max=6,
    filters=(
        MAYHEM,
        Filter("age", "Token age (mins)", "age_min", "<=", 15),
        Filter("dev", "Dev holding %", "dev_pct", "<=", 20, quality=EXACT, audit=True,
               note="creator wallet's current balance, on-chain"),
        Filter("snipers", "Snipers holdings %", "snipers_pct", "<=", 20, quality=APPROX, audit=True,
               note="wallets that bought in the first 3 slots (~1.2 s), excluding the dev"),
        Filter("holders", "Holders", "holders", ">=", 4, quality=EXACT, audit=True),
        Filter("volume", "Volume ($)", "vol_usd", ">=", 4_000, quality=EXACT, note="DexScreener"),
        Filter("mc", "Market cap ($)", "mc_usd", ">=", 6_000, quality=EXACT, note="DexScreener"),
        Filter("fees", "Total fees (SOL)", "fees_sol", ">=", 0.1, quality=ESTIMATE, audit=True,
               note="network + priority fees + Jito tips paid by traders (first slots exact, later sampled)"),
        KEYWORD_FILTER,
    ),
    reasons=(
        "Token age max 15 min (was 25): a coin you looked at and forgot gets a second look, then clears.",
        "Dev holding and snipers limits: personal preference.",
        "Holders min 4: the token is organic, not one big bundle; does not miss runners.",
        "Volume, market cap and fees: trial and error; together they give coins here a better chance.",
        "No socials filter: tech projects and new launchpads often have none linked.",
    ),
)

MIGRATED = Column(
    key="migrated", title="Migrated", stage="migrated", horizon_s=24 * 3600, audit_refresh_s=300, audit_max=30,
    filters=(
        MAYHEM,
        Filter("snipers", "Snipers holdings %", "snipers_pct", "<=", 25, quality=APPROX, audit=True,
               note="wallets that bought in the first 3 slots (~1.2 s), excluding the dev"),
        Filter("mc", "Market cap ($)", "mc_usd", ">=", 6_000, quality=EXACT, note="DexScreener"),
        Filter("fees", "Total fees (SOL)", "fees_sol", ">=", 6, quality=ESTIMATE, audit=True,
               note="network + priority fees + Jito tips paid by traders (first slots exact, later sampled)"),
    ),
    reasons=(
        "Only max snipers in Audit: other audit filters made him miss many good coins.",
        "Total fees min 6 (raised from 4): picked by opening and closing many tokens.",
        "No socials filter: everything here is already filtered.",
    ),
)

STRATEGY = Strategy(
    key="daumen",
    name="Daumen - New Filters",
    author="Daumen",
    source_url="https://www.youtube.com/watch?v=qONQbEUQx9Y",
    platform="Terminal (trade.padre.gg), Solana memecoins",
    summary=("Token-discovery filters for three board columns (New, Soon, Migrated). Goal: reduce noise in "
             "New and Soon without missing any runners. No entry, exit, sizing or stop-loss rules."),
    columns=(NEW, SOON, MIGRATED),
    notes=(
        "Values come from trial and error and he changes them often.",
        "New: clean in the European session; the North American session is more chaotic.",
        "Tested and rejected for New: dev holding min 1% (devs move supply between wallets).",
    ),
)
