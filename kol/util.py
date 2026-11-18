"""Small helpers: base58, pump.fun bonding-curve maths, time."""
from __future__ import annotations

import math
import time

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    out = []
    while n:
        n, r = divmod(n, 58)
        out.append(_B58[r])
    pad = len(b) - len(b.lstrip(b"\0"))
    return "1" * pad + "".join(reversed(out))


def now() -> float:
    return time.time()


# pump.fun bonding curve: constant product on virtual reserves.
# start: 30 virtual SOL, 1,073,000,191 virtual tokens; 793,100,000 tokens are sold before migration.
V_SOL0 = 30.0
V_TOK0 = 1_073_000_191.0
SELLABLE = 793_100_000.0
K = V_SOL0 * V_TOK0
SUPPLY = 1_000_000_000.0


def progress_from_mc_sol(mc_sol: float | None) -> float | None:
    """Bonding-curve progress (0-100 %) implied by a market cap in SOL (pump.fun tokens only)."""
    if not mc_sol or mc_sol <= 0:
        return None
    # mc_sol = price * supply = (vSol / vTok) * SUPPLY and vSol * vTok = K  ->  vSol = sqrt(mc_sol * K / SUPPLY)
    v_sol = math.sqrt(mc_sol * K / SUPPLY)
    v_tok = K / v_sol
    p = (V_TOK0 - v_tok) / SELLABLE * 100
    return max(0.0, min(100.0, p))


def median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2
