from __future__ import annotations

import json
from typing import Any

from .config import LLM_GAME_RULES_PATH


ACTION_NAMES = {
    32: "stop",
    37: "left",
    38: "up",
    39: "right",
    40: "down",
    88: "dig_right",
    90: "dig_left",
}


def read_agent_rules() -> str:
    try:
        return LLM_GAME_RULES_PATH.read_text(encoding="utf-8")[:3000]
    except FileNotFoundError:
        return (
            "Classic level 1 focus: collect all gold, use ladders and route digs to change rows, "
            "and avoid non-progress loops. In god mode, guard contact is non-lethal."
        )


def build_agent_prompt(
    snapshot: dict[str, Any],
    *,
    candidates: list[dict[str, Any]],
    analysis: dict[str, Any],
    include_reasoning: bool = False,
) -> str:
    response_format = (
        '{"candidateId":"candidate_id_here","reasoning":"brief rationale"}'
        if include_reasoning
        else '{"candidateId":"candidate_id_here"}'
    )
    rationale_instruction = (
        "The reasoning field must be a concise, observable decision rationale grounded in the supplied state and candidates; do not reveal hidden chain-of-thought."
        if include_reasoning
        else None
    )
    return "\n\n".join(
        [item for item in [
            "You are choosing one backend-generated candidate for the next short Lode Runner input burst.",
            (
                "The backend has generated executable candidates and assigned scores, targets, "
                "and safety intents. Candidates may represent different tactical tradeoffs; "
                "apply execution gates and the risk policy before comparing progress. Candidate "
                "targets, scores, and reasons are backend-derived. Do not reject a candidate "
                "because its first short action appears indirect, and do not invent unsupported "
                "route interpretations."
            ),
            f"Return JSON only: {response_format}.",
            rationale_instruction,
            "Agent rules:\n" + read_agent_rules(),
            format_decision_context(snapshot, candidates, analysis),
        ] if item is not None]
    )


def format_decision_context(
    snapshot: dict[str, Any],
    candidates: list[dict[str, Any]],
    analysis: dict[str, Any],
) -> str:
    payload = {
        "state": build_state_context(snapshot, analysis),
        "candidates": [format_candidate(candidate) for candidate in candidates],
    }
    return "Decision context (valid JSON):\n" + json.dumps(
        compact_value(payload), sort_keys=True, separators=(",", ":")
    )


def format_state_summary(snapshot: dict[str, Any], analysis: dict[str, Any]) -> str:
    return "Current state (valid JSON):\n" + json.dumps(
        compact_value(build_state_context(snapshot, analysis)),
        sort_keys=True,
        separators=(",", ":"),
    )


def build_state_context(
    snapshot: dict[str, Any], analysis: dict[str, Any]
) -> dict[str, Any]:
    runner = _dict(analysis.get("runner"))
    gold = _dict(analysis.get("gold"))
    risk = _dict(analysis.get("risk"))
    movement = _dict(analysis.get("movement"))
    ladder = _dict(analysis.get("ladder"))
    route_access = _dict(analysis.get("routeAccess"))
    loop_report = _dict(analysis.get("loopReport"))
    primary_target = _dict(analysis.get("primaryProgressTarget"))
    return compact_value(
        {
            "game": {
                "playData": snapshot.get("playData"),
                "level": snapshot.get("level"),
                "gameState": snapshot.get("gameStateName"),
                "godMode": bool(snapshot.get("godMode")),
            },
            "runner": {
                "x": runner.get("x"),
                "y": runner.get("y"),
                "action": runner.get("action"),
                "xOffset": runner.get("xOffset"),
                "yOffset": runner.get("yOffset"),
            },
            "gold": {
                "complete": bool(gold.get("complete", snapshot.get("goldComplete"))),
                "remaining": gold.get("remainingCount", snapshot.get("goldCount")),
                "visible": gold.get("visiblePositions", []),
            },
            "primaryProgressTarget": primary_target,
            "threat": {
                "risk": risk.get("risk"),
                "pressureGuard": format_guard(risk.get("pressureGuard")),
                "nearbyGuards": [
                    format_guard(guard) for guard in risk.get("nearbyGuards") or []
                ],
            },
            "movement": {
                "legalDirections": [
                    direction
                    for direction, field in (
                        ("left", "canMoveLeft"),
                        ("right", "canMoveRight"),
                        ("up", "canMoveUp"),
                        ("down", "canMoveDown"),
                    )
                    if movement.get(field)
                ],
                "openHoles": format_open_holes(movement),
            },
            "route": {
                "ladder": format_ladder(ladder),
                "access": format_route_access(route_access),
            },
            "loop": {
                "active": bool(loop_report.get("active")),
                "type": loop_report.get("type"),
                "suppressedCount": len(loop_report.get("suppressedCandidates") or []),
            },
        }
    )


def format_candidates(candidates: list[dict[str, Any]]) -> str:
    return "Candidate choices (valid JSON):\n" + json.dumps(
        compact_value([format_candidate(candidate) for candidate in candidates]),
        sort_keys=True,
        separators=(",", ":"),
    )


def format_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    action = _dict(candidate.get("firstAction"))
    reasons = list(candidate.get("reasons") or [])
    action_reason = action.get("reason")
    if action_reason and action_reason not in reasons:
        reasons.append(action_reason)
    return compact_value(
        {
            "id": candidate.get("id"),
            "kind": candidate.get("kind"),
            "score": candidate.get("score"),
            "target": candidate.get("target"),
            "action": {
                "name": ACTION_NAMES.get(action.get("keyCode"), "unknown"),
                "ticks": action.get("ticks"),
            },
            "intents": candidate.get("intents") or [candidate.get("kind")],
            "targets": candidate.get("targets") or (
                [candidate.get("target")] if candidate.get("target") else []
            ),
            "reasons": reasons,
        }
    )


def format_guard(value: Any) -> dict[str, Any]:
    guard = _dict(value)
    has_gold = guard.get("hasGold")
    guard_id = (
        guard.get("id")
        if (
            isinstance(has_gold, (int, float))
            and not isinstance(has_gold, bool)
            and has_gold > 0
        )
        else None
    )
    return compact_value(
        {
            "id": guard_id,
            "x": guard.get("x"),
            "y": guard.get("y"),
            "relativeX": guard.get("relativeX"),
            "relativeY": guard.get("relativeY"),
            "distance": guard.get("distance"),
            "motion": guard.get("motion"),
            "closing": guard.get("closing"),
            "risk": guard.get("risk"),
            "hasGold": guard.get("hasGold"),
        }
    )


def format_open_holes(movement: dict[str, Any]) -> dict[str, Any]:
    details = _dict(movement.get("details"))
    result = {}
    for side in ("left", "right"):
        detail = _dict(details.get(side))
        hole = _dict(detail.get("openHole"))
        result[side] = compact_value(
            {
                "openDugHoleDistance": detail.get("openDugHoleDistance"),
                "hole": {
                    "x": hole.get("x"),
                    "y": hole.get("y"),
                    "distance": hole.get("distance"),
                    "occupiedByTrappedGuard": hole.get("occupiedByTrappedGuard"),
                },
            }
        )
    return compact_value(result)


def format_ladder(ladder: dict[str, Any]) -> dict[str, Any]:
    nearest = _dict(ladder.get("nearestRowLadder"))
    return compact_value(
        {
            "onLadder": ladder.get("onLadder"),
            "onExitLadder": ladder.get("onExitLadder"),
            "adjacent": ladder.get("adjacentToLadder"),
            "recommendedAction": ladder.get("recommendedAction"),
            "nearest": {
                "x": nearest.get("x"),
                "y": nearest.get("y"),
                "tile": nearest.get("tile"),
                "distance": nearest.get("distance"),
                "direction": nearest.get("direction"),
            },
        }
    )


def format_route_access(route_access: dict[str, Any]) -> dict[str, Any]:
    drop_threat = _dict(route_access.get("dropThreat"))
    nearest_threat = _dict(drop_threat.get("nearestThreat"))
    return compact_value(
        {
            "available": route_access.get("available"),
            "recommendedAction": route_access.get("recommendedAction"),
            "followAvailable": route_access.get("followAvailable"),
            "followAction": route_access.get("followAction"),
            "followBlockedByGuard": route_access.get("followBlockedByGuard"),
            "digBlockedByGuard": route_access.get("digBlockedByGuard"),
            "accessCell": route_access.get("openedAccessCell")
            or route_access.get("plannedAccessCell"),
            "dropThreat": {
                "unsafe": drop_threat.get("unsafe"),
                "nearest": format_guard(nearest_threat),
            },
            "reason": route_access.get("reason"),
        }
    )


def compact_value(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            compacted = compact_value(item)
            if compacted is None or compacted == "" or compacted == {} or compacted == []:
                continue
            result[key] = compacted
        return result
    if isinstance(value, list):
        return [
            compacted
            for item in value
            if (compacted := compact_value(item))
            is not None
            and compacted != ""
            and compacted != {}
            and compacted != []
        ]
    return value


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
