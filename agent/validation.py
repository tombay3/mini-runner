from __future__ import annotations

from typing import Any

from .config import AGENT_ALLOWED_KEYCODES, AGENT_LEVEL, AGENT_MAX_TICKS, AGENT_PLAY_DATA


def validate_agent_request(payload: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise ValueError("request body must be an object")
    try:
        play_data = int(payload.get("playData", 0))
        level = int(payload.get("level", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("playData and level must be integers") from exc
    if play_data != AGENT_PLAY_DATA or level != AGENT_LEVEL:
        raise ValueError("only Classic level 1 is supported")

    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be an object")

    history = payload.get("history", [])
    if not isinstance(history, list):
        raise ValueError("history must be an array")

    return snapshot, history


def normalize_agent_action(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("agent action must be an object")

    key_code = value.get("keyCode")
    if isinstance(key_code, str):
        key_code = AGENT_ALLOWED_KEYCODES.get(key_code)
    try:
        key_code = int(key_code)
    except (TypeError, ValueError) as exc:
        raise ValueError("action.keyCode must be an allowed keycode") from exc
    if key_code not in set(AGENT_ALLOWED_KEYCODES.values()):
        raise ValueError("action.keyCode is not allowed")

    try:
        ticks = int(value.get("ticks", 1))
    except (TypeError, ValueError) as exc:
        raise ValueError("action.ticks must be an integer") from exc
    ticks = max(1, min(AGENT_MAX_TICKS, ticks))

    reason = value.get("reason", "")
    return {"keyCode": key_code, "ticks": ticks, "reason": str(reason)[:500]}
