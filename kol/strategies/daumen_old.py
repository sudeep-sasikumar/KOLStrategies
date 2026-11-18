"""Daumen - Old Filters ("2026 Memecoin Trading Tutorial (New Updates!)", YouTube, 7 Oct 2026).
See docs/strategies/daumen-old-filters.md. Only the column filters are testable as rules; the rest of the
video (tracked wallets, bundle reading, holder-reward icons, entries) is discretionary and listed in notes."""
from __future__ import annotations

from .base import APPROX, ESTIMATE, EXACT, Column, Filter, Strategy

MAYHEM = Filter("mayhem", "Mayhem mode", "mayhem", "is_false", quality=EXACT, unknown_ok=True,
                note="from the creation event; unknown for tokens created before the collector started")
SNIPERS_NOTE = "wallets that bought in the first 3 slots (~1.2 s), excluding the dev"
FEES_NOTE = "network + priority fees + Jito tips paid by traders (first slots exact, later sampled)"

NEW = Column(
    key="new", title="New", stage="new", horizon_s=5 * 60,
    filters=(
        MAYHEM,
        Filter("mc_max", "Market cap max ($)", "mc_usd", "<=", 30_000, note="no minimum"),
        Filter("socials", "At least one social", "socials", "is_true", quality=APPROX,
               note="X, Telegram or website in the token metadata. pump.fun's automatic 'coin community' "
                    "link is recorded but not counted"),
        # One part of the keyword text is blurred in the video; only the readable phrase is used.
        Filter("keywords", "Exclude keywords", "text", "excludes_any", ("FREE ENTRY",), quality=APPROX,
               note="name + symbol; the blurred part of his list is not known"),
    ),
    reasons=(
        "All protocols selected: we see pump.fun creations only (launchpads built on Pump included; Stonk not).",
        "Mayhem mode hidden: the token buys and sells for you - an on-chain casino.",
        "At least one social: without one it is very hard to know what the token is about. New column only.",
        "No age filter in his New column: we count a token as a hit if it passes within 5 minutes of "
        "creation (our choice, adjustable).",
    ),
)

SOON = Column(
    key="soon", title="Soon", stage="bonding", horizon_s=25 * 60, audit_refresh_s=120, audit_max=10,
    filters=(
        MAYHEM,
        Filter("age", "Token age (mins)", "age_min", "<=", 24),
        Filter("insiders", "Insiders holdings %", "insiders_pct", "<=", 25, quality=APPROX, audit=True,
               note="non-dev wallets that bought in the creation slot itself (bundled with the launch). "
                    "Terminal's exact insider definition is not public"),
        Filter("dev", "Dev holding %", "dev_pct", "<=", 25, quality=EXACT, audit=True,
               note="creator wallet's current balance, on-chain"),
        Filter("snipers", "Snipers holdings %", "snipers_pct", "<=", 25, quality=APPROX, audit=True,
               note=SNIPERS_NOTE),
        Filter("volume", "Volume ($)", "vol_usd", ">=", 4_000, note="DexScreener"),
        Filter("mc", "Market cap ($)", "mc_usd", ">=", 6_000, note="DexScreener"),
        Filter("fees", "Total fees (SOL)", "fees_sol", ">=", 0.05, quality=ESTIMATE, audit=True, note=FEES_NOTE),
    ),
    reasons=(
        "Token age max 24 min: keeps the middle column clean.",
        "Insiders, dev and snipers max 25%: removes a few coins, not many.",
        "Volume and market cap: some volume and a market cap that isn't 3K-4K give a higher chance it is organic.",
        "Total fees min 0.05 SOL: poor bundles don't generate much in fees; an organic token should "
        "(he sometimes uses 0.2).",
        "No socials filter: good gems sometimes appear here without socials.",
    ),
)

MIGRATED = Column(
    key="migrated", title="Migrated", stage="migrated", horizon_s=24 * 3600, audit_refresh_s=300, audit_max=30,
    filters=(
        MAYHEM,
        Filter("snipers", "Snipers holdings %", "snipers_pct", "<=", 25, quality=APPROX, audit=True,
               note=SNIPERS_NOTE),
        Filter("mc", "Market cap ($)", "mc_usd", ">=", 6_000, note="DexScreener"),
        Filter("fees", "Total fees (SOL)", "fees_sol", ">=", 6, quality=ESTIMATE, audit=True, note=FEES_NOTE),
    ),
    reasons=(
        "No other restrictions on this column.",
        "Same values as his newer Migrated filters, so both tabs show the same Migrated results.",
    ),
)

STRATEGY = Strategy(
    key="daumen_old",
    name="Daumen - Old Filters",
    author="Daumen",
    source_url="https://www.youtube.com/watch?v=KBgcOGWEARY",
    platform="Terminal (trade.padre.gg), Solana memecoins",
    summary=("His October 2026 board filters for New, Soon and Migrated, plus discretionary rules. Soon is the "
             "column he says he makes most of his money in. No exit, take-profit, stop or sizing rules."),
    columns=(NEW, SOON, MIGRATED),
    notes=(
        "Soon is where he makes most of his money; Migrated is the column a low-cap trencher uses least.",
        "He hides tokens he researched and rejected (H) so the Soon column stays readable.",
        "Not measured here - needs his tracked-wallet list (Google Doc) or Terminal-only data: tracked-wallet "
        "buys of $40+, 'K bubbles', fresh-wallet and same-bot holder flags, holder-reward / fee-distribution "
        "icons, Stonk tokens.",
        "Bundle red flag he uses: a 1-second chart straight up to 20K-30K with no tracked-wallet buys. "
        "Not testable without his wallet list.",
        "Entries: early (around 7K) is fine if he likes the coin; higher (e.g. 20K) only with confluence and "
        "earlier bids. He avoids tweet plays and up-only charts without information.",
    ),
)
