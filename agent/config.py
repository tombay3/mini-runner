from __future__ import annotations

import os
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
PUZZLE_RULES_PATH = ROOT_DIR / "docs" / "puzzle-game.md"
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"

AGENT_PLAY_DATA = 1
AGENT_LEVEL = 1
AGENT_MAX_TICKS = 20
AGENT_ALLOWED_KEYCODES = {
    "stop": 32,
    "left": 37,
    "right": 39,
    "up": 38,
    "down": 40,
    "dig_left": 90,
    "dig_right": 88,
}


def get_openai_api_key() -> str | None:
    return os.environ.get("OPENAI_API_KEY")


def get_openai_model() -> str | None:
    return os.environ.get("OPENAI_MODEL")
