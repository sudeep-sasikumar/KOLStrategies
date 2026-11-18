from .base import Strategy
from .daumen import STRATEGY as DAUMEN

# Every strategy here gets a dashboard tab and is evaluated on every token the collector follows.
STRATEGIES: tuple[Strategy, ...] = (DAUMEN,)
BY_KEY = {s.key: s for s in STRATEGIES}
