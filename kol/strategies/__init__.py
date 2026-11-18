from .base import Strategy
from .daumen import STRATEGY as DAUMEN
from .daumen_old import STRATEGY as DAUMEN_OLD

# Every strategy here gets a dashboard tab and is evaluated on every token the collector follows.
STRATEGIES: tuple[Strategy, ...] = (DAUMEN, DAUMEN_OLD)
BY_KEY = {s.key: s for s in STRATEGIES}
