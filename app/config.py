"""Config loading: config/config.json (+ env overrides for secrets)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = ROOT / "migrations"


@dataclass
class Config:
    telegram_token: str
    owner_ids: List[int] = field(default_factory=list)
    telegram_proxy: str = ""
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout: int = 60
    db_path: str = str(ROOT / "data" / "secretary.db")


def load_config(path: str = "") -> Config:
    path = path or os.environ.get("SECRETARY_CONFIG") or str(ROOT / "config" / "config.json")
    with open(path, encoding="utf-8-sig") as f:
        raw = json.load(f)
    llm = raw.get("llm", {})
    db_path = raw.get("db_path", "data/secretary.db")
    if db_path != ":memory:" and not os.path.isabs(db_path):
        db_path = str(ROOT / db_path)
    return Config(
        telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN") or raw["telegram_token"],
        owner_ids=[int(x) for x in raw.get("owner_telegram_ids", [])],
        telegram_proxy=raw.get("telegram_proxy", ""),
        llm_base_url=llm.get("base_url", "http://localhost:11434/v1"),
        llm_api_key=os.environ.get("LLM_API_KEY") or llm.get("api_key", ""),
        llm_model=llm.get("model", ""),
        llm_timeout=int(llm.get("timeout_seconds", 60)),
        db_path=db_path,
    )
