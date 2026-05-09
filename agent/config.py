from __future__ import annotations

import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
AGENT_RULES_PATH = ROOT_DIR / "public" / "AGENT_RULES.md"

AGENT_PLAY_DATA = 1
AGENT_LEVEL = 1
AGENT_MAX_TICKS = 20
AGENT_TOOL_MAX_TURNS = 3
AGENT_TEMPERATURE = 0.1
AGENT_ALLOWED_KEYCODES = {
    "stop": 32,
    "left": 37,
    "right": 39,
    "up": 38,
    "down": 40,
    "dig_left": 90,
    "dig_right": 88,
}


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


def get_benchmark_models() -> list[str]:
    raw = os.environ.get("AGENT_BENCHMARK_MODELS", "")
    models = []
    for part in raw.split(","):
        normalized = normalize_model_name(part)
        if normalized:
            models.append(normalized)
    return models
