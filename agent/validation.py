from __future__ import annotations

from typing import Any

from .config import AGENT_LEVEL, AGENT_PLAY_DATA
from .errors import AgentRequestError


def validate_agent_request(payload: Any) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(payload, dict):
        raise AgentRequestError("request body must be an object")
    try:
        play_data = int(payload.get("playData", 0))
        level = int(payload.get("level", 0))
    except (TypeError, ValueError) as exc:
        raise AgentRequestError("playData and level must be integers") from exc
    if play_data != AGENT_PLAY_DATA or level != AGENT_LEVEL:
        raise AgentRequestError("only Classic level 1 is supported")

    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict):
        raise AgentRequestError("snapshot must be an object")

    history = payload.get("history", [])
    if not isinstance(history, list):
        raise AgentRequestError("history must be an array")

    model = payload.get("model")
    if model is not None and not isinstance(model, str):
        raise AgentRequestError("model must be a string")

    run_mode = payload.get("runMode", "single")
    if run_mode != "single":
        raise AgentRequestError("runMode must be single")

    run_id = payload.get("runId")
    if run_id is not None and not isinstance(run_id, str):
        raise AgentRequestError("runId must be a string")

    return snapshot, history, {
        "model": model,
        "runMode": run_mode,
        "runId": run_id,
    }
