from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .prompt import build_state_context, carrying_gold, format_candidate


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return value[:240] if isinstance(value, str) else ""


def _action(value: Any) -> dict[str, Any]:
    action = _dict(value)
    return {key: action.get(key) for key in ("keyCode", "ticks")}


def summarize_state(snapshot: dict[str, Any], analysis: dict[str, Any] | None = None) -> dict[str, Any]:
    """One compact state contract for decisions and terminal snapshots."""
    analysis = analysis or {}
    runner = _dict(analysis.get("runner")) or _dict(snapshot.get("runner"))
    gold = _dict(analysis.get("gold")) or _dict(snapshot.get("gold"))
    guards = []
    for guard in snapshot.get("guards") or []:
        if not isinstance(guard, dict):
            continue
        guards.append({
            **{key: guard.get(key) for key in ("id", "x", "y", "xOffset", "yOffset")},
            "action": guard.get("actionName", guard.get("action")),
            "carryingGold": carrying_gold(guard.get("hasGold")),
        })
    context = build_state_context(snapshot, analysis)
    return {
        "tick": snapshot.get("tick"),
        "gameState": analysis.get("gameState", snapshot.get("gameStateName", snapshot.get("gameState"))),
        "godMode": bool(analysis.get("godMode", snapshot.get("godMode", False))),
        "runner": {
            **{key: runner.get(key) for key in ("x", "y", "xOffset", "yOffset")},
            "action": runner.get("actionName", runner.get("action")),
        },
        "guards": guards,
        "gold": {
            "remaining": gold.get("remainingCount", snapshot.get("goldCount")),
            "complete": gold.get("complete", snapshot.get("goldComplete")),
            "visible": context.get("gold", {}).get("visible", []) if analysis else
                                [{"x": item.get("x"), "y": item.get("y")}
                                 for item in gold.get("visiblePositions", []) if isinstance(item, dict)],
        },
        "risk": _dict(analysis.get("risk")).get("risk", "unknown"),
        **({key: context.get(key, {}) for key in
            ("goldTarget", "exitTarget", "threat", "movement", "route")}
           if analysis else {}),
    }


def summarize_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    action = _dict(candidate.get("action"))
    context = format_candidate(candidate)
    return {
        **{key: candidate.get(key) for key in ("id", "kind", "lane", "score")},
        "target": context.get("target"),
        "reasons": context.get("reasons", []),
        "action": {**_action(action), "name": context["action"]["name"]},
    }


def summarize_candidates(candidates: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [summarize_candidate(candidate) for candidate in candidates or []]


def serialize_step_trace(
    *, snapshot: dict[str, Any], action: dict[str, Any],
    candidates: list[dict[str, Any]] | None = None,
    selected_candidate: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
    loop_monitor: dict[str, Any] | None = None,
    analysis: dict[str, Any] | None = None,
    model_selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validation, loop, selection = validation or {}, loop_monitor or {}, model_selection or {}
    events = []
    for item in (analysis or {}).get("candidateAudit", []):
        if item.get("disposition") in {"exposed", "proposed"}:
            continue
        events.append({
            "id": item.get("candidateId"), "kind": item.get("kind"),
            "status": item.get("disposition"), "action": _action(item.get("proposedAction")),
            "reason": _text(item.get("detail")),
        })
    return {
        "createdAt": utc_now(),
        "state": summarize_state(snapshot, analysis),
        "candidates": summarize_candidates(candidates),
        "decision": {
            "requestedId": selection.get("requestedCandidateId", validation.get("requestedCandidateId")),
            "selectedId": (selected_candidate or {}).get("id"),
            "rationale": _text(selection.get("declaredRationale")),
            "fallback": {"code": "candidate_fallback", "message": _text(validation.get("fallbackReason"))}
                        if validation.get("fallbackUsed") else None,
        },
        "action": _action(action),
        "loop": {"active": bool(loop.get("active")), "type": loop.get("type") if loop.get("active") else None,
                 "suppressedCount": len(_dict((analysis or {}).get("loopReport", loop)).get("suppressedCandidates") or [])},
        "candidateEvents": events,
    }
