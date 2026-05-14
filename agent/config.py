from __future__ import annotations

import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
AGENT_RULES_PATH = ROOT_DIR / "public" / "AGENT_RULES.md"

AGENT_PLAY_DATA = 1
AGENT_LEVEL = 1
AGENT_MAX_TICKS = 20
AGENT_TEMPERATURE = 0.1


def normalize_model_name(model: str | None, default_provider: str = "openai") -> str | None:
    if model is None:
        return None
    normalized = str(model).strip()
    if not normalized:
        return None
    if ":" not in normalized:
        normalized = f"{default_provider}:{normalized}"
    return normalized


def get_default_agent_model() -> str | None:
    return normalize_model_name(
        os.environ.get("AGENT_DEFAULT_MODEL") or os.environ.get("OPENAI_MODEL")
    )
