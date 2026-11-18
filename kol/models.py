"""Records kept for every token and every strategy hit. The SQLite columns are these fields."""
from __future__ import annotations

from dataclasses import dataclass, field, fields


@dataclass
class Token:
    mint: str
    first_seen: float = 0.0
    # from the creation event (PumpPortal)
    name: str = ""
    symbol: str = ""
    uri: str = ""
    dev: str = ""
    bonding_curve: str = ""
    pool: str = ""
    created_at: float | None = None
    seen_create: int = 0
    mayhem: int | None = None
    initial_buy: float | None = None          # tokens the dev bought in the creation transaction
    dev_initial_pct: float | None = None
    mc_sol_create: float | None = None
    migrated_at: float | None = None
    # market data (DexScreener)
    pair: str = ""
    dex_id: str = ""
    mc_usd: float | None = None
    liq_usd: float | None = None
    vol_usd: float | None = None              # total volume since creation (bonding curve + AMM)
    vol_bc_usd: float | None = None           # volume on the bonding curve (frozen at migration)
    buys: int | None = None
    sells: int | None = None
    progress_pct: float | None = None
    # on-chain audit (Solana RPC)
    holders: int | None = None
    dev_pct: float | None = None
    top10_pct: float | None = None
    snipers: int | None = None
    snipers_pct: float | None = None
    insiders_pct: float | None = None         # holdings of non-dev wallets that bought in the creation slot
    bundle_buyers: int | None = None          # non-dev buyers in the creation slot
    tx_count: int | None = None               # bonding-curve transactions (incl. failed ones: they pay fees too)
    tx_complete: int = 0
    amm_txns: int | None = None               # AMM buys + sells after migration (DexScreener, 24 h)
    early_n: int = 0                          # transactions in the first 3 slots (fetched one by one)
    fee_early_sol: float = 0.0                # their exact network + priority + Jito tip cost
    fee_samples: int = 0                      # later transactions sampled for the average cost
    fee_sample_sol: float = 0.0
    fees_net_sol: float | None = None
    fees_trade_sol: float | None = None
    fees_sol: float | None = None             # estimate, see README "Total fees"
    audited_at: float | None = None
    audits: int = 0
    token_program: str = ""
    supply_raw: float | None = None
    sig_newest: str = ""
    create_slot: int | None = None
    sniper_list: str = ""                     # JSON list of sniper wallets
    insider_list: str = ""                    # JSON list of creation-slot buyers (bundled with the launch)
    # socials (token metadata)
    twitter: str = ""
    telegram: str = ""
    website: str = ""
    community: str = ""                       # pump.fun's auto "coin community" page (not counted as a social)
    socials_checked: int = 0
    # outcome tracking
    peak_mc: float | None = None
    peak_at: float | None = None
    mc_5m: float | None = None
    mc_15m: float | None = None
    mc_1h: float | None = None
    mc_6h: float | None = None
    mc_24h: float | None = None
    last_update: float | None = None
    next_poll: float = 0.0
    done: int = 0
    dex_misses: int = 0

    @property
    def born(self) -> float:
        return self.created_at or self.first_seen

    @property
    def has_socials(self) -> bool:
        return bool(self.twitter or self.telegram or self.website)


@dataclass
class Hit:
    strategy: str
    col: str
    mint: str
    hit_at: float
    mc_at_hit: float | None = None
    snapshot: str = ""
    peak_mc: float | None = None
    peak_at: float | None = None
    mc_5m: float | None = None
    mc_1h: float | None = None
    mc_6h: float | None = None
    mc_24h: float | None = None
    migrated: int = 0
    id: int | None = field(default=None)


TOKEN_FIELDS = [f.name for f in fields(Token)]
HIT_FIELDS = [f.name for f in fields(Hit) if f.name != "id"]
