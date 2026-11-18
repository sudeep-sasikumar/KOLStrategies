"""Loads kol/market/config.json (chains, source URLs, label threshold, schedule)."""
from __future__ import annotations

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).with_name("config.json")


def load(path: Path = CONFIG_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
