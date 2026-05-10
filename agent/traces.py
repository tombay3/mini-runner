from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .reasoning_tools import (
    assess_safe_progress_options,
    detect_progress_stall,
    get_dig_affordance,
    get_escape_affordance,
    get_ladder_affordance,
    get_movement_affordance,
    get_route_access_affordance,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def coerce_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): coerce_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [coerce_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return coerce_jsonable(value.model_dump())
    if hasattr(value, "__dict__"):
        return coerce_jsonable(vars(value))
    return str(value)


def summarize_snapshot(snapshot: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    runner = snapshot.get("runner") or {}
    guards = snapshot.get("guards") or []
    return {
        "gameState": snapshot.get("gameStateName"),
        "tick": snapshot.get("tick"),
        "godMode": snapshot.get("godMode"),
        "goldCount": snapshot.get("goldCount"),
        "goldComplete": snapshot.get("goldComplete"),
        "gold": snapshot.get("gold"),
        "runner": {
            "x": runner.get("x"),
            "y": runner.get("y"),
            "action": runner.get("actionName"),
            "xOffset": runner.get("xOffset"),
            "yOffset": runner.get("yOffset"),
        },
        "guards": [
            {
                "id": guard.get("id"),
                "x": guard.get("x"),
                "y": guard.get("y"),
                "action": guard.get("actionName"),
                "sameRowAsRunner": guard.get("sameRowAsRunner"),
            }
            for guard in guards[:6]
            if isinstance(guard, dict)
        ],
        "ladderAffordance": get_ladder_affordance(snapshot),
        "movementAffordance": get_movement_affordance(snapshot),
        "digAffordance": get_dig_affordance(snapshot),
        "routeAccessAffordance": get_route_access_affordance(snapshot),
        "escapeAffordance": get_escape_affordance(snapshot),
        "stallSummary": detect_progress_stall(snapshot, history),
        "progressOptions": assess_safe_progress_options(snapshot, history, limit=4),
    }


def serialize_step_trace(
    *,
    snapshot: dict[str, Any],
    history: list[dict[str, Any]],
    run_mode: str,
    requested_model: str,
    selected_model: str,
    action: dict[str, Any],
    planner: dict[str, Any],
    response: Any,
    benchmark: dict[str, Any] | None,
    guardrail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    final_message = None
    intermediate_messages = []
    if hasattr(response, "choices") and response.choices:
        final_message = getattr(response.choices[0], "message", None)
        intermediate_messages = getattr(response.choices[0], "intermediate_messages", []) or []

    return {
        "createdAt": utc_now(),
        "runMode": run_mode,
        "requestedModel": requested_model,
        "selectedModel": selected_model,
        "snapshot": summarize_snapshot(snapshot, history),
        "historyTail": coerce_jsonable(history[-8:]),
        "action": coerce_jsonable(action),
        "planner": coerce_jsonable(planner),
        "benchmark": coerce_jsonable(benchmark),
        "guardrail": coerce_jsonable(guardrail),
        "finalMessage": coerce_jsonable(final_message),
        "intermediateMessages": coerce_jsonable(intermediate_messages),
        "response": {
            "id": getattr(response, "id", None),
            "model": getattr(response, "model", None),
        },
    }
