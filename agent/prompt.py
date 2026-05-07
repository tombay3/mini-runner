from __future__ import annotations

import json

from .config import PUZZLE_RULES_PATH


def read_puzzle_rules() -> str:
    try:
        return PUZZLE_RULES_PATH.read_text(encoding="utf-8")[:6000]
    except FileNotFoundError:
        return "Collect all gold, avoid guards, use ladders and ropes, and dig traps to solve the level."


def build_agent_prompt(snapshot: dict, history: list[dict]) -> str:
    return "\n\n".join(
        [
            "You are choosing the next short Lode Runner input burst for Classic level 1.",
            "You may call helper tools before answering, but your final answer must be JSON only.",
            "Return exactly one next action burst. Choose one allowed keycode and a tick count from 1 to 20.",
            "Allowed keycodes: stop=32, left=37, right=39, up=38, down=40, dig_left=90, dig_right=88.",
            'Return this JSON shape: {"keyCode": 39, "ticks": 4, "reason": "brief explanation"}.',
            "Prefer short, safe bursts that avoid guards, reduce loops, and preserve puzzle progress.",
            "Game rules:\n" + read_puzzle_rules(),
            "Current live snapshot:\n" + json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
            "Recent actions:\n" + json.dumps(history[-20:], ensure_ascii=False, sort_keys=True),
        ]
    )
