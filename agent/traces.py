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
    runner = _dict(analysis.get("runner"))
    gold = _dict(analysis.get("gold"))
    risk = _dict(analysis.get("risk"))
    movement = _dict(analysis.get("movement"))
    ladder = _dict(analysis.get("ladder"))
    route_access = _dict(analysis.get("routeAccess"))
    return {
        "gameState": analysis.get("gameState"),
        "tick": snapshot.get("tick"),
        "godMode": analysis.get("godMode"),
        "runner": {
            "x": runner.get("x"),
            "y": runner.get("y"),
            "action": runner.get("action"),
            "xOffset": runner.get("xOffset"),
            "yOffset": runner.get("yOffset"),
        },
        "gold": {
            "complete": gold.get("complete", analysis.get("goldComplete")),
            "remainingCount": gold.get("remainingCount", analysis.get("goldCount")),
            "visiblePositions": gold.get("visiblePositions", []),
        },
        "primaryProgressTarget": analysis.get("primaryProgressTarget"),
        "guardRisk": {
            "risk": risk.get("risk"),
            "nearestSameRowGuard": risk.get("nearestSameRowGuard"),
        },
        "movement": {
            "canMoveLeft": movement.get("canMoveLeft"),
            "canMoveRight": movement.get("canMoveRight"),
            "canMoveUp": movement.get("canMoveUp"),
            "canMoveDown": movement.get("canMoveDown"),
        },
        "ladder": {
            "detail": ladder.get("detail"),
        },
        "routeAccess": {
            "available": route_access.get("available"),
            "recommendedAction": route_access.get("recommendedAction"),
            "followAvailable": route_access.get("followAvailable"),
            "followAction": route_access.get("followAction"),
            "reason": route_access.get("reason"),
        },
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


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def serialize_step_trace(
    *,
    snapshot: dict[str, Any],
    history: list[dict[str, Any]],
    action: dict[str, Any],
    candidates: list[dict[str, Any]] | None = None,
    selected_candidate: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
    stall_supervisor: dict[str, Any] | None = None,
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
        "stallSupervisor": coerce_jsonable(stall_supervisor),
    }
