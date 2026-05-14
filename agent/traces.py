from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .candidates import analyze_state


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
    analysis = analyze_state(snapshot, history)
    return {
        "gameState": analysis.get("gameState"),
        "tick": snapshot.get("tick"),
        "godMode": analysis.get("godMode"),
        "goldCount": analysis.get("goldCount"),
        "goldComplete": analysis.get("goldComplete"),
        "runner": analysis.get("runner"),
        "guards": analysis.get("guards"),
        "gold": analysis.get("gold"),
        "nearestGold": analysis.get("nearestGold"),
        "primaryProgressTarget": analysis.get("primaryProgressTarget"),
        "rowLadders": analysis.get("rowLadders"),
        "risk": analysis.get("risk"),
        "movement": analysis.get("movement"),
        "dig": analysis.get("dig"),
        "ladder": analysis.get("ladder"),
        "routeAccess": analysis.get("routeAccess"),
        "stallReport": analysis.get("stallReport") or analysis.get("progressMonitor"),
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
    guardrail: dict[str, Any] | None = None,
    candidates: list[dict[str, Any]] | None = None,
    selected_candidate: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
    analysis: dict[str, Any] | None = None,
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
        "analysis": coerce_jsonable(analysis),
        "candidates": coerce_jsonable(candidates),
        "selectedCandidate": coerce_jsonable(selected_candidate),
        "validation": coerce_jsonable(validation),
        "historyTail": coerce_jsonable(history[-8:]),
        "action": coerce_jsonable(action),
        "planner": coerce_jsonable(planner),
        "guardrail": coerce_jsonable(guardrail),
        "finalMessage": coerce_jsonable(final_message),
        "intermediateMessages": coerce_jsonable(intermediate_messages),
        "response": {
            "id": getattr(response, "id", None),
            "model": getattr(response, "model", None),
        },
    }
