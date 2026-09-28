"""Environment-driven settings."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    """Runtime configuration read from environment variables / .env."""

    groq_api_key: str | None
    groq_model: str
    groq_fallback_model: str
    hindsight_base_url: str | None
    hindsight_api_key: str | None
    bank_id: str
    data_dir: Path
    var_dir: Path


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings."""
    var_dir = Path(os.getenv("LEDGERLENS_VAR_DIR", ROOT / "var"))
    var_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        groq_api_key=os.getenv("GROQ_API_KEY") or None,
        groq_model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        groq_fallback_model=os.getenv("GROQ_FALLBACK_MODEL", "qwen/qwen3-32b"),
        hindsight_base_url=os.getenv("HINDSIGHT_BASE_URL") or None,
        hindsight_api_key=os.getenv("HINDSIGHT_API_KEY") or None,
        bank_id=os.getenv("HINDSIGHT_BANK_ID", "ledgerlens-ap"),
        data_dir=ROOT / "data",
        var_dir=var_dir,
    )
