"""Settings from the environment (and an optional .env file next to the project).

Environment:
  TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID  optional - startup notice only (signals are off for now)
  DASHBOARD_PASSWORD     required whenever the dashboard is reachable beyond localhost
  DASHBOARD_BIND         default 127.0.0.1 (the Docker image sets 0.0.0.0)
  DASHBOARD_PORT         default 8030
  DASHBOARD_COOKIE_SECURE true when served over HTTPS (set in docker-compose.yaml)
  KOL_DATA_DIR           default ./data (the Docker image uses /app/data, a volume)
  SOLANA_RPC_URL         default the public mainnet RPC; a private one (Helius, QuickNode...) is faster
  SOLANA_RPC_RPS         requests per second allowed on that RPC (default 4 public, 10 private)
  DOMAIN                 used for the dashboard link in the Telegram startup notice
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLIC_RPC = "https://api.mainnet-beta.solana.com"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass
class Settings:
    data_dir: Path
    bind: str
    port: int
    password: str
    cookie_secure: bool
    tg_token: str
    tg_chat: str
    rpc_url: str
    rpc_rps: float
    pumpportal_ws: str
    domain: str
    base_path: str
    version: str

    @property
    def db_path(self) -> Path:
        return self.data_dir / "kol.sqlite"

    @property
    def public_rpc(self) -> bool:
        return self.rpc_url.rstrip("/") == PUBLIC_RPC


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


def load() -> Settings:
    _load_dotenv(ROOT / ".env")
    e = os.environ.get
    rpc = (e("SOLANA_RPC_URL") or "").strip() or PUBLIC_RPC
    default_rps = 4.0 if rpc.rstrip("/") == PUBLIC_RPC else 10.0
    data_dir = Path(e("KOL_DATA_DIR") or (ROOT / "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        data_dir=data_dir,
        bind=e("DASHBOARD_BIND") or "127.0.0.1",
        port=int(e("DASHBOARD_PORT") or 8030),
        password=e("DASHBOARD_PASSWORD") or "",
        cookie_secure=_truthy(e("DASHBOARD_COOKIE_SECURE")),
        tg_token=(e("TELEGRAM_BOT_TOKEN") or "").strip(),
        tg_chat=(e("TELEGRAM_CHAT_ID") or "").strip(),
        rpc_url=rpc,
        rpc_rps=float(e("SOLANA_RPC_RPS") or default_rps),
        pumpportal_ws=e("PUMPPORTAL_WS") or "wss://pumpportal.fun/api/data",
        domain=(e("DOMAIN") or "").strip(),
        base_path=(e("BASE_PATH") or "/kol").rstrip("/"),
        version=(e("APP_VERSION") or "dev")[:12],
    )


# ---- collector tuning --------------------------------------------------------------------------
# How often each token is looked at. Every token is followed for 24 h so the dashboard can tell
# which filters caught the runners and which runners were missed.
LIVE_WINDOW_S = 20 * 60          # poll every token closely for its first 20 minutes
LIVE_POLL_S = 20
HOT_MC_USD = 20_000              # tokens above this market cap are polled every minute
HOT_POLL_S = 60
WARM_MC_USD = 7_000              # tokens above this are re-checked every 10 minutes for 24 h
WARM_POLL_S = 600
TRACK_S = 24 * 3600              # follow every token (and every hit) for 24 hours
CHECKPOINTS = (("5m", 300), ("15m", 900), ("1h", 3600), ("6h", 21600), ("24h", 86400))
HIT_CHECKPOINTS = (("5m", 300), ("1h", 3600), ("6h", 21600), ("24h", 86400))

# On-chain look-ups (holders, dev %, snipers, fees) are only made for tokens that already pass a
# column's cheap filters, or that reach this market cap early (for the pattern study).
AUDIT_MC_USD = 10_000
AUDIT_EARLY_S = 30 * 60
SNIPER_SLOTS = 2                 # buyers in the creation slot + the next 2 slots (~1.2 s) are snipers
SNIPER_TX_CAP = 30
FEE_SAMPLE_TXS = 5

# pump.fun trading fee charged on every trade (protocol + creator); recorded apart from "total fees"
BONDING_FEE_RATE = 0.0125
AMM_FEE_RATE = 0.0030

# outcome labels
RUNNER_MC_USD = 100_000          # a token whose market cap reaches this within 24 h is a "runner"
