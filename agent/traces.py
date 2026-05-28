from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


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


def summarize_state(snapshot: dict[str, Any], analysis: dict[str, Any] | None) -> dict[str, Any]:
    analysis = analysis or {}
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


def summarize_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": candidate.get("id"),
        "kind": candidate.get("kind"),
        "score": candidate.get("score"),
        "baseScore": candidate.get("baseScore"),
        "stallBlocked": candidate.get("stallBlocked", False),
        "stallRecovery": candidate.get("stallRecovery", False),
        "target": candidate.get("target"),
        "firstAction": candidate.get("firstAction"),
        "goal": candidate.get("goal"),
        "reason": candidate.get("reason"),
    }


def summarize_candidates(candidates: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [summarize_candidate(candidate) for candidate in candidates or []]


def serialize_step_trace(
    *,
    snapshot: dict[str, Any],
    history: list[dict[str, Any]],
    action: dict[str, Any],
    planner: dict[str, Any],
    candidates: list[dict[str, Any]] | None = None,
    selected_candidate: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
    analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "createdAt": utc_now(),
        "state": coerce_jsonable(summarize_state(snapshot, analysis)),
        "candidates": coerce_jsonable(summarize_candidates(candidates)),
        "selectedCandidateId": (selected_candidate or {}).get("id"),
        "selectedCandidateKind": (selected_candidate or {}).get("kind"),
        "validation": coerce_jsonable(validation),
        "historyTail": coerce_jsonable(history[-8:]),
        "action": coerce_jsonable(action),
        "planner": coerce_jsonable(planner),
        "stallSupervisor": coerce_jsonable((planner or {}).get("stallSupervisor")),
    }
