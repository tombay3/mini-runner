from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .config import AGENT_MAX_TICKS
from .reasoning_tools import (
    DIG_LEFT_KEYCODE,
    DIG_RIGHT_KEYCODE,
    DOWN_KEYCODE,
    LEFT_KEYCODE,
    RIGHT_KEYCODE,
    STOP_KEYCODE,
    UP_KEYCODE,
    assess_guard_risk,
    assess_emergency_hole_escape_threat,
    find_nearest_gold_candidates,
    find_row_ladders,
    get_dig_affordance,
    get_ladder_affordance,
    get_movement_affordance,
    get_route_access_affordance,
)
from .loop_tools import (
    build_loop_report,
    candidate_suppression_reason,
    record_suppressed_candidate,
)


ACTION_NAMES = {
    STOP_KEYCODE: "stop",
    LEFT_KEYCODE: "left",
    RIGHT_KEYCODE: "right",
    UP_KEYCODE: "up",
    DOWN_KEYCODE: "down",
    DIG_LEFT_KEYCODE: "dig_left",
    DIG_RIGHT_KEYCODE: "dig_right",
}

CANDIDATE_LANES = json.loads(
    Path(__file__).with_name("candidate_lanes.json").read_text(encoding="utf-8")
)


def candidate_lane(kind: str | None) -> str:
    return CANDIDATE_LANES.get(kind or "", "fallback")

GUARD_PRESSURE_RISKS = {"medium", "high", "critical"}

PROSPECTIVE_HORIZONTAL_KINDS = {
    "align_ladder",
    "classic_gold_route",
    "collect_same_row_gold",
    "exit_ladder_route",
    "low_risk_horizontal_progress",
    "retreat_from_guard",
}

CLASSIC_LEVEL_WIDTH = 28
LEGACY_SUBTILE_STEP = 8

DIG_KEYCODES = {
    "dig_left": DIG_LEFT_KEYCODE,
    "dig_right": DIG_RIGHT_KEYCODE,
}

CLASSIC_EXIT_ROW_WAYPOINTS = {
    14: 27,
    13: 27,
    12: 20,
    11: 20,
    10: 20,
    9: 20,
    8: 20,
    7: 20,
    6: 25,
    5: 25,
    4: 25,
    3: 18,
    2: 18,
    1: 18,
}

CLASSIC_LOWER_GOLD_ROW_WAYPOINTS = {
    3: 25,
    4: 25,
    5: 25,
    6: 20,
    7: 20,
    8: 20,
    9: 20,
    10: 20,
    11: 20,
    12: 27,
}

CLASSIC_LEFT_GOLD_ROW_WAYPOINTS = {
    14: 27,
    13: 27,
    9: 20,
    10: 20,
    11: 20,
}

CLASSIC_UPPER_LEFT_GOLD_ROW_WAYPOINTS = {
    1: 7,
    2: 7,
    3: 7,
    4: 14,
    5: 14,
    6: 14,
}


def analyze_state(snapshot: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    runner = _dict(snapshot.get("runner"))
    gold = _dict(snapshot.get("gold"))
    nearest_gold = find_nearest_gold_candidates(snapshot, limit=5)
    row_ladders = find_row_ladders(snapshot, limit=6)
    primary_progress_target = find_primary_progress_target(nearest_gold)
    risk = assess_guard_risk(snapshot)
    movement = get_movement_affordance(snapshot)
    dig = get_dig_affordance(snapshot, risk=risk)
    analysis = {
        "gameState": snapshot.get("gameStateName"),
        "godMode": bool(snapshot.get("godMode")),
        "goldComplete": bool(gold.get("complete", snapshot.get("goldComplete"))),
        "goldCount": snapshot.get("goldCount"),
        "runner": {
            "x": runner.get("x"),
            "y": runner.get("y"),
            "action": runner.get("actionName"),
            "xOffset": runner.get("xOffset"),
            "yOffset": runner.get("yOffset"),
        },
        "gold": {
            "remainingCount": gold.get("remainingCount"),
            "complete": gold.get("complete"),
            "visiblePositions": gold.get("visiblePositions", []),
            "carriedByGuards": gold.get("carriedByGuards", []),
        },
        "nearestGold": nearest_gold,
        "primaryProgressTarget": primary_progress_target,
        "rowLadders": row_ladders,
        "risk": risk,
        "movement": movement,
        "dig": dig,
        "ladder": get_ladder_affordance(snapshot, row_ladders=row_ladders),
        "routeAccess": get_route_access_affordance(
            snapshot,
            dig=dig,
            nearest_gold=nearest_gold,
            row_ladders=row_ladders,
        ),
        "activeDig": _dict(snapshot.get("activeDig")),
    }
    analysis["loopReport"] = build_loop_report(analysis, history)
    return analysis


def generate_candidates(
    snapshot: dict[str, Any],
    history: list[dict[str, Any]],
    *,
    limit: int = 7,
    max_action_ticks: int = AGENT_MAX_TICKS,
    mode: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    mode = candidate_mode(mode)
    analysis = analyze_state(snapshot, history)
    movement = analysis["movement"]
    dig = analysis["dig"]
    ladder = analysis["ladder"]
    route_access = analysis["routeAccess"]
    loop_report = analysis["loopReport"]
    risk = analysis["risk"]
    god_mode = bool(analysis["godMode"])
    guard_pressure = not god_mode and risk.get("risk") in GUARD_PRESSURE_RISKS
    gold_complete = bool(analysis["goldComplete"])
    runner = analysis["runner"]
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    candidate_audit: list[dict[str, Any]] = []
    analysis["candidateAudit"] = candidate_audit

    def add(
        *,
        kind: str,
        key_code: int,
        ticks: int,
        score: int,
        target: dict[str, Any] | None = None,
        reason: str,
        candidate_id: str | None = None,
    ) -> None:
        audit = {
            "kind": kind,
            "candidateId": candidate_id or make_candidate_id(
                kind, target, ACTION_NAMES[key_code]
            ),
            "lane": candidate_lane(kind),
            "target": target,
            "proposedAction": {
                "keyCode": key_code,
                "ticks": ticks,
            },
            "disposition": "proposed",
        }
        candidate_audit.append(audit)
        action = _normalize_action(key_code, ticks, reason, max_ticks=max_action_ticks)
        action = limit_horizontal_ticks_under_guard_pressure(action, analysis)
        action = limit_horizontal_ticks_before_open_hole(action, movement, kind)
        action = apply_prospective_horizontal_endpoint_safety(
            action, analysis, kind, snapshot=snapshot
        )
        if action is None:
            audit["disposition"] = "safety_rejection"
            audit["detail"] = "prospective endpoint safety rejected the action"
            return
        if not is_action_physically_valid(
            action,
            movement,
            dig,
            candidate_kind=kind,
            runner_x_offset=_to_int(_dict(analysis.get("runner")).get("xOffset")),
        ):
            audit["disposition"] = "physical_rejection"
            return
        if not is_action_guard_safe(action, analysis, candidate_kind=kind):
            audit["disposition"] = "safety_rejection"
            return
        cid = candidate_id or make_candidate_id(kind, target, ACTION_NAMES[key_code])
        audit["candidateId"] = cid
        audit["validatedAction"] = action
        if cid in seen:
            audit["disposition"] = "deduplicated"
            audit["detail"] = "candidate id already proposed"
            return
        seen.add(cid)
        candidate = {"id": cid, "kind": kind, "firstAction": action}
        suppression_reason = candidate_suppression_reason(candidate, loop_report)
        if suppression_reason:
            record_suppressed_candidate(loop_report, candidate, suppression_reason)
            audit["disposition"] = "loop_suppressed"
            audit["detail"] = suppression_reason
            return
        next_candidate = {
            "id": cid,
            "kind": kind,
            "lane": candidate_lane(kind),
            "score": score,
            "target": target,
            "firstAction": action,
            "intents": [kind],
            "targets": [target] if target else [],
            "reasons": [reason],
        }
        signature = (action["keyCode"], action["ticks"])
        for index, existing in enumerate(candidates):
            existing_action = existing["firstAction"]
            if signature != (existing_action["keyCode"], existing_action["ticks"]):
                continue
            if not candidates_semantically_mergeable(existing, next_candidate):
                continue
            merged = merge_candidate_metadata(existing, next_candidate)
            if (-score, cid) < (-int(existing["score"]), str(existing["id"])):
                candidates[index] = {**merged, **next_candidate, **{
                    "intents": merged["intents"],
                    "targets": merged["targets"],
                    "reasons": merged["reasons"],
                }}
            else:
                candidates[index] = merged
            audit["disposition"] = "deduplicated"
            audit["detail"] = f"merged into {candidates[index]['id']}"
            return
        candidates.append(next_candidate)
        audit["disposition"] = "validated"

    def finalize() -> tuple[list[dict[str, Any]], dict[str, Any]]:
        candidates.sort(key=lambda item: (-int(item["score"]), item["id"]))
        exposed = candidates[:limit]
        exposed_ids = {str(item.get("id")) for item in exposed}
        for audit in candidate_audit:
            if audit.get("disposition") != "validated":
                continue
            if str(audit.get("candidateId")) in exposed_ids:
                audit["disposition"] = "exposed"
            else:
                audit["disposition"] = "limit_truncated"
        return exposed, analysis

    add_dig_completion_wait_candidate(add, analysis)
    if _dict(analysis.get("activeDig")).get("active"):
        return finalize()
    add_floor_refill_wait_candidate(add, analysis)
    if add_trap_resolution_wait_candidate(add, movement, risk):
        return finalize()

    if gold_complete:
        add_exit_candidates(add, analysis, movement)

    if guard_pressure:
        add_non_god_escape_candidates(add, snapshot, movement, dig, risk)

    if ladder.get("onLadder"):
        direction = choose_ladder_direction(snapshot, analysis)
        target = _dict(analysis.get("primaryProgressTarget"))
        direction_toward_target = ladder_direction_toward_target(analysis, direction)
        add(
            kind="climb_ladder",
            key_code=UP_KEYCODE if direction == "up" else DOWN_KEYCODE,
            ticks=6,
            score=(
                122
                if direction_toward_target and loop_report.get("type") == "vertical_cycle"
                else 108
                if direction_toward_target
                else 112
                if loop_report.get("active")
                else 95
                if not gold_complete
                else 105
            ),
            target={"x": runner_x, "y": runner_y, "tile": "S" if ladder.get("onExitLadder") else "H"},
            reason=ladder_reason(ladder, direction, target),
        )
        # A vertical-cycle filter can suppress the preferred climb direction.
        # Keep one physically valid opposite exit available so filtering does
        # not collapse an otherwise traversable ladder state to emergency_hold.
        loop_vertical = loop_report.get("type") == "vertical_cycle"
        blocked_directions = set(
            _dict(loop_report.get("suppress")).get("directions") or []
        )
        alternate = "down" if direction == "up" else "up"
        if (
            loop_vertical
            and direction in blocked_directions
            and alternate not in blocked_directions
            and movement.get("canMoveDown" if alternate == "down" else "canMoveUp")
        ):
            add(
                kind="climb_ladder",
                key_code=DOWN_KEYCODE if alternate == "down" else UP_KEYCODE,
                ticks=6,
                score=112,
                target={"x": runner_x, "y": runner_y, "tile": "H"},
                reason=(
                    f"vertical-cycle recovery: use the opposite ladder direction ({alternate})"
                ),
                candidate_id=f"climb_ladder_{runner_x}_{runner_y}_{alternate}",
            )
        if classic_upper_left_ladder_detour_active(analysis):
            if low_risk_expansion_enabled(mode) and _eligible_for_low_risk_expansion(
                analysis, candidates
            ):
                add_distinct_low_risk_progress_alternatives(
                    add, analysis, snapshot, candidates[0], mode=mode
                )
            return finalize()

    if not gold_complete:
        add_classic_gold_route_candidate(add, analysis)
        classic_route_active = any(
            candidate.get("kind") == "classic_gold_route" for candidate in candidates
        )
        if classic_route_active and classic_upper_left_detour(analysis):
            if low_risk_expansion_enabled(mode) and _eligible_for_low_risk_expansion(
                analysis, candidates
            ):
                add_distinct_low_risk_progress_alternatives(
                    add, analysis, snapshot, candidates[0], mode=mode
                )
            return finalize()
        add_gold_candidates(add, analysis, god_mode, snapshot)
        if not classic_route_active:
            add_ladder_alignment_candidates(add, analysis, god_mode)
        add_route_access_candidate(add, route_access)
        add_route_access_follow_candidate(add, analysis, route_access)
        add_guard_clearance_wait_candidate(add, route_access)
        add_descent_candidates(add, analysis, movement)
    else:
        add_ladder_alignment_candidates(add, analysis, god_mode)

    if god_mode and not gold_complete and not candidates:
        add_god_mode_progress_candidate(add, analysis)

    # Preserve a bounded horizontal progress option for low-risk off-row
    # states when structured routes produced nothing. Without this, a legal
    # movement toward remaining gold collapses to wait_or_stop.
    if (
        not candidates
        and not guard_pressure
        and not loop_report.get("active")
        and not gold_complete
    ):
        add_low_risk_horizontal_progress_candidate(add, analysis)

    if low_risk_expansion_enabled(mode) and _eligible_for_low_risk_expansion(
        analysis, candidates
    ):
        singleton = candidates[0]
        add_distinct_low_risk_progress_alternatives(
            add, analysis, snapshot, singleton, mode=mode
        )

    if not candidates and not (guard_pressure or loop_report.get("active")):
        add_wait_candidate(add)

    if not candidates:
        add_emergency_hold_candidate(add, risk)

    return finalize()


def low_risk_expansion_enabled(mode: str | None = None) -> bool:
    return candidate_mode(mode) in {"alternatives", "guided", "promoted"}


def candidate_mode(override: str | None = None) -> str:
    return str(
        override if override is not None else os.environ.get("AGENT_CANDIDATE_MODE", "baseline")
    ).strip().lower()


def experimental_progress_score(base: int, mode: str | None = None) -> int:
    """Raise only experimental progress scores in the promoted arm."""
    return base + 18 if candidate_mode(mode) == "promoted" else base


def _eligible_for_low_risk_expansion(
    analysis: dict[str, Any], candidates: list[dict[str, Any]]
) -> bool:
    risk = _dict(analysis.get("risk"))
    loop_report = _dict(analysis.get("loopReport"))
    return (
        len(candidates) == 1
        and candidate_lane(candidates[0].get("kind")) == "progress"
        and not analysis.get("godMode")
        and not analysis.get("goldComplete")
        and not _dict(analysis.get("activeDig")).get("active")
        and not loop_report.get("active")
        and risk.get("risk") not in GUARD_PRESSURE_RISKS
    )


def add_distinct_low_risk_progress_alternatives(
    add,
    analysis: dict[str, Any],
    snapshot: dict[str, Any],
    singleton: dict[str, Any],
    *,
    mode: str | None = None,
) -> None:
    """Expose only legal progress choices with a distinct direction and target."""
    movement = _dict(analysis.get("movement"))
    singleton_action = _dict(singleton.get("firstAction"))
    singleton_key_code = _to_int(singleton_action.get("keyCode"))
    singleton_target = singleton.get("target")
    runner_y = _to_int(_dict(analysis.get("runner")).get("y"))
    seen_targets: set[tuple[int, int, str]] = set()
    for gold in analysis.get("nearestGold", []):
        if gold.get("source") == "guard" or not gold.get("sameRow"):
            continue
        direction = gold.get("direction")
        if direction not in {"left", "right"}:
            continue
        target = (_to_int(gold.get("x")), _to_int(gold.get("y")), direction)
        if target in seen_targets or None in target[:2]:
            continue
        seen_targets.add(target)
        if not same_row_terrain_path_clear(snapshot, gold):
            continue
        if not movement.get("canMoveLeft" if direction == "left" else "canMoveRight"):
            continue
        key_code = LEFT_KEYCODE if direction == "left" else RIGHT_KEYCODE
        candidate_target = {"x": target[0], "y": target[1], "tile": "$"}
        if key_code == singleton_key_code or candidate_target == singleton_target:
            continue
        add(
            kind="low_risk_progress_option",
            key_code=key_code,
            ticks=6,
            score=experimental_progress_score(88, mode),
            target=candidate_target,
            reason=(
                f"distinct low-risk route: move {direction} toward gold at "
                f"({target[0]},{target[1]})"
            ),
            candidate_id=(
                f"low_risk_progress_option_{target[0]}_{target[1]}_{direction}"
            ),
        )

    for ladder in analysis.get("rowLadders", []):
        direction = ladder.get("direction")
        if ladder.get("tile") != "H" or direction not in {"left", "right"}:
            continue
        key_code = LEFT_KEYCODE if direction == "left" else RIGHT_KEYCODE
        candidate_target = {"x": ladder.get("x"), "y": ladder.get("y"), "tile": "H"}
        if key_code == singleton_key_code or candidate_target == singleton_target:
            continue
        if not movement.get("canMoveLeft" if direction == "left" else "canMoveRight"):
            continue
        add(
            kind="low_risk_progress_option",
            key_code=key_code,
            ticks=6,
            score=experimental_progress_score(86, mode),
            target=candidate_target,
            reason=(
                f"distinct low-risk route: move {direction} toward ladder at "
                f"({ladder.get('x')},{ladder.get('y')})"
            ),
            candidate_id=(
                f"low_risk_progress_option_ladder_{ladder.get('x')}_"
                f"{ladder.get('y')}_{direction}"
            ),
        )

    if _dict(analysis.get("ladder")).get("onLadder") and runner_y is not None:
        for direction, key_code, movement_key in (
            ("up", UP_KEYCODE, "canMoveUp"),
            ("down", DOWN_KEYCODE, "canMoveDown"),
        ):
            if key_code == singleton_key_code or not movement.get(movement_key):
                continue
            target_gold = next(
                (
                    gold
                    for gold in analysis.get("nearestGold", [])
                    if gold.get("source") != "guard"
                    and _to_int(gold.get("y")) is not None
                    and (
                        int(gold["y"]) < runner_y
                        if direction == "up"
                        else int(gold["y"]) > runner_y
                    )
                ),
                None,
            )
            if not target_gold:
                continue
            candidate_target = {
                "x": target_gold.get("x"),
                "y": target_gold.get("y"),
                "tile": "$",
            }
            if candidate_target == singleton_target:
                continue
            add(
                kind="low_risk_progress_option",
                key_code=key_code,
                ticks=6,
                score=experimental_progress_score(87, mode),
                target=candidate_target,
                reason=(
                    f"distinct low-risk ladder route: climb {direction} toward gold at "
                    f"({target_gold.get('x')},{target_gold.get('y')})"
                ),
                candidate_id=(
                    f"low_risk_progress_option_ladder_{direction}_gold_"
                    f"{target_gold.get('x')}_{target_gold.get('y')}"
                ),
            )


def candidates_semantically_mergeable(
    existing: dict[str, Any], incoming: dict[str, Any]
) -> bool:
    """Only merge duplicate actions when their model-facing intent is equivalent."""
    return (
        existing.get("kind") == incoming.get("kind")
        and existing.get("target") == incoming.get("target")
    )


def merge_candidate_metadata(
    existing: dict[str, Any], incoming: dict[str, Any]
) -> dict[str, Any]:
    merged = dict(existing)
    for field in ("intents", "targets", "reasons"):
        values = list(existing.get(field) or [])
        for value in incoming.get(field) or []:
            if value not in values:
                values.append(value)
        merged[field] = values
    return merged


def add_exit_candidates(add, analysis: dict[str, Any], movement: dict[str, Any]) -> None:
    ladder = analysis["ladder"]
    runner = analysis["runner"]
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    if movement.get("canFinishExitClimb"):
        add(
            kind="exit_ladder_route",
            key_code=UP_KEYCODE,
            ticks=4,
            score=150,
            target={"x": 18, "y": 0, "tile": "S"},
            reason="runner is at (18,0) but remains below exit center by a positive yOffset",
        )
        return
    if ladder.get("onExitLadder"):
        add(
            kind="exit_ladder_route",
            key_code=UP_KEYCODE,
            ticks=6,
            score=130,
            target={"x": runner_x, "y": runner_y, "tile": "S"},
            reason="runner is already on the revealed exit ladder",
        )
        return
    for ladder_item in analysis["rowLadders"]:
        if ladder_item.get("tile") != "S":
            continue
        direction = ladder_item.get("direction")
        key_code = LEFT_KEYCODE if direction == "left" else RIGHT_KEYCODE if direction == "right" else UP_KEYCODE
        add(
            kind="exit_ladder_route",
            key_code=key_code,
            ticks=20,
            score=125,
            target={"x": ladder_item["x"], "y": ladder_item["y"], "tile": "S"},
            reason="gold is complete and revealed exit ladder is on the runner row",
        )
        return
    if movement.get("canMoveUp"):
        add(
            kind="exit_ladder_route",
            key_code=UP_KEYCODE,
            ticks=20,
            score=115,
            target={"x": runner_x, "y": runner_y},
            reason="gold is complete and upward movement is valid",
        )
        return

    waypoint_x = CLASSIC_EXIT_ROW_WAYPOINTS.get(runner_y)
    if waypoint_x is not None:
        exit_waypoint = next(
            (
                item
                for item in analysis["rowLadders"]
                if item.get("tile") in {"H", "S"} and _to_int(item.get("x")) == waypoint_x
            ),
            None,
        )
        if exit_waypoint and runner_x != waypoint_x:
            direction = "left" if runner_x is not None and runner_x > waypoint_x else "right"
            add(
                kind="exit_ladder_route",
                key_code=LEFT_KEYCODE if direction == "left" else RIGHT_KEYCODE,
                ticks=ticks_for_exit_alignment(runner_x, waypoint_x),
                score=132,
                target={"x": waypoint_x, "y": runner_y, "tile": exit_waypoint.get("tile")},
                reason=f"Classic level-1 exit chain uses x={waypoint_x} from row {runner_y}",
                candidate_id=f"exit_ladder_route_{waypoint_x}_{runner_y}_{direction}",
            )


def add_classic_gold_route_candidate(add, analysis: dict[str, Any]) -> None:
    target = _dict(analysis.get("primaryProgressTarget"))
    target_x = _to_int(target.get("x"))
    target_y = _to_int(target.get("y"))
    gold = _dict(analysis.get("gold"))
    only_guard_carried_gold = bool(gold.get("carriedByGuards")) and not bool(
        gold.get("visiblePositions")
    )
    runner = _dict(analysis.get("runner"))
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    if runner_x is None or runner_y is None:
        return
    if runner_y == 1 and only_guard_carried_gold:
        waypoint_x = 7
        route_reason = "guard-carried gold via the row-1 descent entry"
        score = 130
        if runner_x == waypoint_x:
            if _dict(analysis.get("movement")).get("canMoveDown"):
                add(
                    kind="classic_gold_route",
                    key_code=DOWN_KEYCODE,
                    ticks=4,
                    score=score,
                    target={"x": waypoint_x, "y": 2, "tile": "H"},
                    reason=(
                        "Classic level-1 guard-carried recovery descends through the "
                        "x=7 row-1 ladder entry"
                    ),
                    candidate_id="classic_gold_route_7_2_down",
                )
            return
    elif target_x == 23 and target_y == 3 and runner_y == 1:
        waypoint_x = 7
        route_reason = "upper gold at (23,3) via the row-1 descent entry"
        score = 130
    elif target_x == 23 and target_y == 3 and runner_y > 3:
        waypoint_x = CLASSIC_EXIT_ROW_WAYPOINTS.get(runner_y)
        route_reason = "upper gold at (23,3)"
        score = 130
        if not any(
            _to_int(item.get("x")) == waypoint_x
            for item in analysis.get("rowLadders") or []
        ):
            return
    elif target_y == 14:
        waypoint_x = CLASSIC_LOWER_GOLD_ROW_WAYPOINTS.get(runner_y)
        route_reason = "row-14 gold"
        score = 132
    elif target_x == 7 and target_y == 12:
        waypoint_x = CLASSIC_LEFT_GOLD_ROW_WAYPOINTS.get(runner_y)
        route_reason = "left-side gold at (7,12)"
        score = 132
    elif target_x == 4 and target_y == 6:
        waypoint_x = CLASSIC_UPPER_LEFT_GOLD_ROW_WAYPOINTS.get(runner_y)
        route_reason = "upper-left gold at (4,6)"
        score = 132
    else:
        return
    if waypoint_x is None or runner_x == waypoint_x:
        return
    direction = "left" if waypoint_x < runner_x else "right"
    add(
        kind="classic_gold_route",
        key_code=LEFT_KEYCODE if direction == "left" else RIGHT_KEYCODE,
        ticks=8,
        score=score,
        target={"x": waypoint_x, "y": runner_y, "tile": "H"},
        reason=(
            f"Classic level-1 {route_reason} is reached through waypoint x={waypoint_x} "
            f"from row {runner_y}"
        ),
    )


def classic_upper_left_detour(analysis: dict[str, Any]) -> bool:
    target = _dict(analysis.get("primaryProgressTarget"))
    return _to_int(target.get("x")) == 4 and _to_int(target.get("y")) == 6


def classic_upper_left_ladder_detour_active(analysis: dict[str, Any]) -> bool:
    runner = _dict(analysis.get("runner"))
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    return bool(
        classic_upper_left_detour(analysis)
        and runner_x == 14
        and runner_y is not None
        and 4 <= runner_y <= 6
    )


def add_non_god_escape_candidates(
    add,
    snapshot: dict[str, Any],
    movement: dict[str, Any],
    dig: dict[str, Any],
    risk: dict[str, Any],
) -> None:
    guard = _dict(risk.get("pressureGuard"))
    side = guard.get("relativeX")
    closing = bool(guard.get("closing"))
    guard_risk = guard.get("risk")
    left_dig = _dict(dig.get("left"))
    right_dig = _dict(dig.get("right"))
    active_trap = _trap_hole_between_pressure_guard(movement, risk)
    same_row_guards = [
        _dict(item)
        for item in risk.get("nearbyGuards") or []
        if isinstance(item, dict) and item.get("relativeY") == "same"
    ]
    pinch = (
        any(item.get("relativeX") == "left" and item.get("risk") in GUARD_PRESSURE_RISKS for item in same_row_guards)
        and any(item.get("relativeX") == "right" and item.get("risk") in GUARD_PRESSURE_RISKS for item in same_row_guards)
    )
    left_dig_available = active_trap.get("side") != "left" and (bool(dig.get("canDigLeft")) or bool(
        left_dig.get("canDefensiveDig") and left_dig.get("guardCouldFall")
    ))
    right_dig_available = active_trap.get("side") != "right" and (bool(dig.get("canDigRight")) or bool(
        right_dig.get("canDefensiveDig") and right_dig.get("guardCouldFall")
    ))
    left_trap_ready = guard_risk in {"high", "critical"} or bool(
        left_dig.get("guardCouldFall")
    )
    right_trap_ready = guard_risk in {"high", "critical"} or bool(
        right_dig.get("guardCouldFall")
    )
    edge_defensive_trap = bool(
        risk.get("runnerOnEdge")
        and closing
        and (
            (side == "left" and left_dig_available and left_trap_ready)
            or (side == "right" and right_dig_available and right_trap_ready)
        )
    )
    runner = _dict(snapshot.get("runner"))
    runner_x = _to_int(runner.get("x"))
    guard_x = _to_int(guard.get("x"))
    guard_distance = _to_int(guard.get("distance"))
    guard_motion = str(guard.get("motion") or "unknown")
    # Horizontal side retreat is only justified when the pressure guard is on
    # the runner's row.  A high/critical guard above or below may still need
    # the dedicated hole, vertical, or defensive candidates below, but must
    # not masquerade as a same-row guard and suppress ordinary progress.
    side_retreat_pressure = guard.get("relativeY") == "same"
    # A high/critical guard directly below or above can be escaped by taking
    # the opposite valid ladder direction. Treat that as vertical retreat
    # pressure too; otherwise a runner on a ladder can collapse to
    # emergency_hold even though a row-changing escape is available.
    cross_row_up_pressure = (
        guard_risk in {"high", "critical"}
        and guard.get("relativeY") == "below"
        and movement.get("canMoveUp")
    )
    cross_row_down_pressure = (
        guard_risk in {"high", "critical"}
        and guard.get("relativeY") == "above"
        and movement.get("canMoveDown")
    )
    decisive_defensive_trap = bool(
        guard_risk == "high"
        and closing
        and guard_distance == 3
        and (
            (side == "left" and left_dig_available and left_trap_ready)
            or (side == "right" and right_dig_available and right_trap_ready)
        )
    )
    imminent_landing_side = (
        side
        if guard.get("relativeY") == "above"
        and guard_motion in {"down", "fall"}
        and guard_distance is not None
        and guard_distance <= 3
        else None
    )
    edge_escape_direction = None
    if (
        guard.get("relativeY") == "below"
        and guard_distance is not None
        and guard_distance <= 3
        and runner_x is not None
        and guard_x is not None
    ):
        if (
            not movement.get("canMoveRight")
            and movement.get("canMoveLeft")
            and guard_x <= runner_x
            and guard_motion in {"right", "up", "climb_out"}
        ):
            edge_escape_direction = "left"
        elif (
            not movement.get("canMoveLeft")
            and movement.get("canMoveRight")
            and guard_x >= runner_x
            and guard_motion in {"left", "up", "climb_out"}
        ):
            edge_escape_direction = "right"
    if edge_escape_direction:
        add(
            kind="evade_edge_ladder",
            key_code=LEFT_KEYCODE if edge_escape_direction == "left" else RIGHT_KEYCODE,
            ticks=4,
            score=124,
            reason=(
                f"guard below is moving toward the edge ladder; step {edge_escape_direction} "
                "before it enters the runner's column"
            ),
            candidate_id=f"evade_edge_ladder_{edge_escape_direction}",
        )
        # Keep evaluating vertical escape options as well. The horizontal
        # edge move can be rejected later by same-row guard safety, while an
        # available ladder retreat remains a valid way out of the pressure.
    left_open_hole = _dict(_dict(_dict(movement.get("details")).get("left")).get("openHole"))
    right_open_hole = _dict(_dict(_dict(movement.get("details")).get("right")).get("openHole"))
    hole_escape_direction = None
    if guard.get("relativeY") in {"above", "below"} and not closing:
        if (
            _to_int(left_open_hole.get("distance")) == 1
            and not left_open_hole.get("occupiedByTrappedGuard")
            and movement.get("canMoveRight")
            and _to_int(right_open_hole.get("distance")) != 1
        ):
            hole_escape_direction = "right"
        elif (
            _to_int(right_open_hole.get("distance")) == 1
            and not right_open_hole.get("occupiedByTrappedGuard")
            and movement.get("canMoveLeft")
            and _to_int(left_open_hole.get("distance")) != 1
        ):
            hole_escape_direction = "left"
    if hole_escape_direction:
        if hole_escape_direction == imminent_landing_side:
            hole_escape_direction = None
    if hole_escape_direction:
        add(
            kind="evade_open_hole",
            key_code=RIGHT_KEYCODE if hole_escape_direction == "right" else LEFT_KEYCODE,
            ticks=4,
            score=124,
            reason=(
                f"adjacent empty hole blocks the opposite side; move {hole_escape_direction} "
                "while the cross-row guard is not closing"
            ),
            candidate_id=f"evade_open_hole_{hole_escape_direction}",
        )
    if guard_risk in GUARD_PRESSURE_RISKS:
        for direction, key_code, movement_key in (
            ("left", LEFT_KEYCODE, "canMoveLeft"),
            ("right", RIGHT_KEYCODE, "canMoveRight"),
        ):
            movement_detail = _dict(_dict(movement.get("details")).get(direction))
            hole = _dict(movement_detail.get("openHole"))
            hole_y = _to_int(hole.get("y"))
            terrain_height = _to_int(movement.get("terrainHeight"))
            medium_retreat_drop = (
                guard_risk == "medium"
                and closing
                and guard.get("relativeY") == "same"
                and direction != side
            )
            if (
                (guard_risk in {"high", "critical"} or medium_retreat_drop)
                and movement.get(movement_key)
                and _to_int(movement_detail.get("openDugHoleDistance")) == 1
                and hole_y is not None
                and terrain_height is not None
                and hole_y < terrain_height - 1
                and not assess_emergency_hole_escape_threat(snapshot, hole).get("unsafe")
            ):
                add(
                    kind="escape_through_open_hole",
                    key_code=key_code,
                    ticks=4,
                    score=126,
                    target={"x": hole.get("x"), "y": hole.get("y"), "tile": "open_hole"},
                    reason=f"{guard_risk} guard pressure leaves an adjacent open escape hole to the {direction}",
                )
    if (
        (side_retreat_pressure or cross_row_up_pressure)
        and movement.get("canMoveUp")
        and not decisive_defensive_trap
    ):
        add(
            kind="retreat_from_guard",
            key_code=UP_KEYCODE,
            ticks=6,
            score=120,
            reason="non-god-mode same-row guard pressure is active and up is valid",
        )
    if (
        (side_retreat_pressure or cross_row_down_pressure)
        and movement.get("canMoveDown")
        and not edge_defensive_trap
        and not decisive_defensive_trap
    ):
        add(
            kind="retreat_from_guard",
            key_code=DOWN_KEYCODE,
            ticks=6,
            score=118,
            reason="non-god-mode same-row guard pressure is active and down is valid",
        )
    if side == "left" and left_dig_available and left_trap_ready and not edge_escape_direction:
        imminent_landing_trap = imminent_landing_side == "left"
        add(
            kind="defensive_dig",
            key_code=DIG_LEFT_KEYCODE,
            ticks=8,
            score=(
                136
                if imminent_landing_trap
                else 134
                if pinch
                else 132
                if edge_defensive_trap
                else 138
                if decisive_defensive_trap
                else 112
            ),
            reason=(
                "guard above-left is descending toward this row; dig_left now while centered"
                if imminent_landing_trap
                else "guard pressure from left and dig_left is legal"
            ),
        )
    if side == "right" and right_dig_available and right_trap_ready and not edge_escape_direction:
        imminent_landing_trap = imminent_landing_side == "right"
        add(
            kind="defensive_dig",
            key_code=DIG_RIGHT_KEYCODE,
            ticks=8,
            score=(
                136
                if imminent_landing_trap
                else 134
                if pinch
                else 132
                if edge_defensive_trap
                else 138
                if decisive_defensive_trap
                else 112
            ),
            reason=(
                "guard above-right is descending toward this row; dig_right now while centered"
                if imminent_landing_trap
                else "guard pressure from right and dig_right is legal"
            ),
        )
    if decisive_defensive_trap:
        return
    if (
        side_retreat_pressure
        and side == "left"
        and movement.get("canMoveRight")
    ):
        add(
            kind="retreat_from_guard",
            key_code=RIGHT_KEYCODE,
            ticks=6,
            score=108,
            reason=_guard_reposition_reason("left", "right", closing),
        )
    if (
        side_retreat_pressure
        and side == "right"
        and movement.get("canMoveLeft")
    ):
        add(
            kind="retreat_from_guard",
            key_code=LEFT_KEYCODE,
            ticks=6,
            score=108,
            reason=_guard_reposition_reason("right", "left", closing),
        )
    if side == "same":
        for direction, key_code, movement_key in (
            ("left", LEFT_KEYCODE, "canMoveLeft"),
            ("right", RIGHT_KEYCODE, "canMoveRight"),
        ):
            if not movement.get(movement_key):
                continue
            add(
                kind="retreat_from_guard",
                key_code=key_code,
                ticks=4,
                score=110,
                reason=f"guard is vertically aligned on another row; move {direction} to break its approach line",
                candidate_id=f"retreat_from_guard_same_column_{direction}",
            )


def _guard_reposition_reason(guard_side: str, move_direction: str, closing: bool) -> str:
    motion = "closing" if closing else "not currently closing"
    return (
        f"guard is on the {guard_side} and {motion}; move {move_direction} briefly, "
        "then reassess because the guard may follow and distance may not increase"
    )


def add_gold_candidates(
    add,
    analysis: dict[str, Any],
    god_mode: bool,
    snapshot: dict[str, Any],
) -> None:
    movement = analysis["movement"]
    for gold in analysis["nearestGold"]:
        if gold.get("source") == "guard":
            continue
        if not gold.get("sameRow"):
            continue
        direction = gold.get("direction")
        if direction == "same":
            runner = _dict(analysis.get("runner"))
            x_offset = _to_int(runner.get("xOffset")) or 0
            y_offset = _to_int(runner.get("yOffset")) or 0
            if y_offset > 0 and movement.get("canFinishLadderClimb"):
                key_code = UP_KEYCODE
                ticks = min(
                    4,
                    max(
                        1,
                        (abs(y_offset) + LEGACY_SUBTILE_STEP - 1)
                        // LEGACY_SUBTILE_STEP,
                    ),
                )
                center_reason = f"finish ladder alignment from yOffset {y_offset}"
            elif y_offset < 0 and movement.get("canMoveDown"):
                key_code = DOWN_KEYCODE
                ticks = min(
                    4,
                    max(
                        1,
                        (abs(y_offset) + LEGACY_SUBTILE_STEP - 1)
                        // LEGACY_SUBTILE_STEP,
                    ),
                )
                center_reason = f"center vertically from yOffset {y_offset}"
            else:
                key_code = (
                    LEFT_KEYCODE
                    if x_offset > 0
                    else RIGHT_KEYCODE
                    if x_offset < 0
                    else STOP_KEYCODE
                )
                ticks = (
                    min(4, max(2, (abs(x_offset) + 3) // 4))
                    if x_offset
                    else 2
                )
                center_reason = (
                    f"center from xOffset {x_offset}"
                    if x_offset
                    else "advance collision processing"
                )
            add(
                kind="collect_current_tile_gold",
                key_code=key_code,
                ticks=ticks,
                score=122,
                target={"x": gold["x"], "y": gold["y"], "tile": "$"},
                reason=f"gold shares the runner tile; {center_reason}",
            )
            continue
        if direction not in {"left", "right"}:
            continue
        if not same_row_terrain_path_clear(snapshot, gold):
            continue
        key_code = LEFT_KEYCODE if direction == "left" else RIGHT_KEYCODE
        if not movement.get("canMoveLeft" if direction == "left" else "canMoveRight"):
            continue
        add(
            kind="collect_same_row_gold",
            key_code=key_code,
            ticks=8,
            score=106 if god_mode else 100,
            target={"x": gold["x"], "y": gold["y"], "tile": "$"},
            reason=f"same-row gold is {gold['distance']} tiles to the {direction}",
        )


def same_row_terrain_path_clear(
    snapshot: dict[str, Any], target: dict[str, Any]
) -> bool:
    runner = _dict(snapshot.get("runner"))
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    target_x = _to_int(target.get("x"))
    target_y = _to_int(target.get("y"))
    rows = snapshot.get("terrainGrid")
    if (
        runner_x is None
        or runner_y is None
        or target_x is None
        or target_y != runner_y
        or not isinstance(rows, list)
        or not (0 <= runner_y < len(rows))
    ):
        return True
    row = rows[runner_y]
    if not isinstance(row, str):
        return True
    start, end = sorted((runner_x, target_x))
    return all(x < len(row) and row[x] not in {"#", "@"} for x in range(start + 1, end))


def add_ladder_alignment_candidates(add, analysis: dict[str, Any], god_mode: bool) -> None:
    movement = analysis["movement"]
    loop_report = analysis["loopReport"]
    for ladder in analysis["rowLadders"]:
        if ladder.get("tile") != "H" or ladder.get("distance") == 0:
            continue
        direction = ladder.get("direction")
        if direction not in {"left", "right"}:
            continue
        key_code = LEFT_KEYCODE if direction == "left" else RIGHT_KEYCODE
        if not movement.get("canMoveLeft" if direction == "left" else "canMoveRight"):
            continue
        distance = int(ladder.get("distance") or 0)
        fine_align = distance <= 1
        loop_target = loop_report.get("target") == {
            "x": ladder.get("x"),
            "y": ladder.get("y"),
            "kind": "ladder",
        }
        add(
            kind="align_ladder",
            key_code=key_code,
            ticks=ticks_for_alignment(distance),
            score=ladder_alignment_score(
                distance,
                god_mode=god_mode,
                fine_align=fine_align,
                loop_target=loop_target,
            ),
            target={"x": ladder["x"], "y": ladder["y"], "tile": "H"},
            reason=f"visible ladder is {ladder['distance']} tiles to the {direction}",
        )


def ladder_alignment_score(
    distance: int, *, god_mode: bool, fine_align: bool, loop_target: bool
) -> int:
    if loop_target:
        return 118
    if fine_align:
        return 104
    base = 94 if god_mode else 90
    return base + max(0, 12 - min(max(distance, 0), 12))


def add_route_access_candidate(add, route_access: dict[str, Any]) -> None:
    if not route_access.get("available"):
        return
    action_name = route_access.get("recommendedAction")
    if action_name not in DIG_KEYCODES:
        return
    candidate_id = f"route_access_{action_name}"
    off_row_gold = _dict(route_access.get("offRowGoldTarget"))
    add(
        kind="route_access_dig",
        key_code=DIG_KEYCODES[action_name],
        ticks=12,
        score=88,
        target=off_row_gold,
        reason=str(route_access.get("reason", "legal route-access dig is available")),
        candidate_id=candidate_id,
    )


def add_route_access_follow_candidate(
    add, analysis: dict[str, Any], route_access: dict[str, Any]
) -> None:
    if not route_access.get("followAvailable"):
        return
    direction = route_access.get("followAction")
    if direction not in {"left", "right"}:
        return
    movement = analysis["movement"]
    if not movement.get("canMoveLeft" if direction == "left" else "canMoveRight"):
        return
    key_code = LEFT_KEYCODE if direction == "left" else RIGHT_KEYCODE
    off_row_gold = _dict(route_access.get("offRowGoldTarget"))
    opened_cell = _dict(route_access.get("openedAccessCell"))
    add(
        kind="route_access_follow",
        key_code=key_code,
        ticks=8,
        score=104,
        target=opened_cell or off_row_gold,
        reason=str(route_access.get("reason", "access route is open; move into it")),
    )


def add_guard_clearance_wait_candidate(add, route_access: dict[str, Any]) -> None:
    if not (
        route_access.get("followBlockedByGuard") or route_access.get("digBlockedByGuard")
    ):
        return
    opened_cell = _dict(
        route_access.get("openedAccessCell") or route_access.get("plannedAccessCell")
    )
    threat = _dict(_dict(route_access.get("dropThreat")).get("nearestThreat"))
    signature = "_".join(
        str(threat.get(field, "x")) for field in ("id", "x", "y", "xOffset", "yOffset")
    )
    add(
        kind="wait_for_guard_clearance",
        key_code=STOP_KEYCODE,
        ticks=2,
        score=120,
        target=opened_cell,
        reason=str(route_access.get("reason", "guard blocks safe access-route entry")),
        candidate_id=f"wait_for_guard_clearance_{signature}",
    )


def add_dig_completion_wait_candidate(add, analysis: dict[str, Any]) -> None:
    active_dig = _dict(analysis.get("activeDig"))
    if not active_dig.get("active"):
        return
    frame_index = _to_int(active_dig.get("frameIndex")) or 0
    frame_count = _to_int(active_dig.get("frameCount")) or 0
    target = {
        "x": active_dig.get("x"),
        "y": active_dig.get("y"),
        "tile": "#",
    }
    add(
        kind="wait_for_dig_completion",
        key_code=STOP_KEYCODE,
        ticks=2,
        score=142,
        target=target,
        reason=(
            f"legacy dig at ({target['x']},{target['y']}) is still active "
            f"at frame {frame_index}/{frame_count}"
        ),
        candidate_id=(
            f"wait_for_dig_completion_{target['x']}_{target['y']}_{frame_index}_{frame_count}"
        ),
    )


def add_trap_resolution_wait_candidate(
    add, movement: dict[str, Any], risk: dict[str, Any]
) -> bool:
    trap = _trap_hole_between_pressure_guard(movement, risk)
    if not trap:
        return False
    hole = _dict(trap.get("hole"))
    guard = _dict(trap.get("guard"))
    guard_distance = _to_int(guard.get("distance"))
    guard_motion = str(guard.get("motion") or "unknown")
    if guard_motion in {"fall", "up", "climb_out"} or (
        guard_distance is not None and guard_distance <= 2
    ):
        wait_ticks = 2
    elif guard_distance is not None and guard_distance <= 4:
        wait_ticks = 4
    else:
        wait_ticks = 8
    signature = "_".join(
        str(value)
        for value in (
            trap.get("side"),
            hole.get("x"),
            hole.get("y"),
            hole.get("frameIndex"),
            hole.get("frameTime"),
            guard.get("id"),
            guard.get("x"),
            guard.get("y"),
            guard.get("xOffset"),
            guard.get("yOffset"),
            guard.get("motion"),
        )
    )
    add(
        kind="wait_for_trap_resolution",
        key_code=STOP_KEYCODE,
        ticks=wait_ticks,
        score=140,
        target={"x": hole.get("x"), "y": hole.get("y"), "tile": "open_hole"},
        reason=(
            f"open hole at ({hole.get('x')},{hole.get('y')}) already separates "
            f"the {trap.get('side')}-side pressure guard"
        ),
        candidate_id=f"wait_for_trap_resolution_{signature}",
    )
    return True


def add_floor_refill_wait_candidate(add, analysis: dict[str, Any]) -> None:
    target = _dict(analysis.get("primaryProgressTarget"))
    direction = target.get("direction")
    if direction not in {"left", "right"} and analysis.get("goldComplete"):
        runner = _dict(analysis.get("runner"))
        runner_x = _to_int(runner.get("x"))
        runner_y = _to_int(runner.get("y"))
        waypoint_x = CLASSIC_EXIT_ROW_WAYPOINTS.get(runner_y)
        if runner_x is not None and waypoint_x is not None and runner_x != waypoint_x:
            direction = "left" if waypoint_x < runner_x else "right"
    if direction not in {"left", "right"}:
        return
    movement = _dict(analysis.get("movement"))
    detail = _dict(_dict(movement.get("details")).get(direction))
    hole = _dict(detail.get("openHole"))
    if _to_int(hole.get("distance")) != 1 or hole.get("occupiedByTrappedGuard"):
        return
    route_access = _dict(analysis.get("routeAccess"))
    opened_access_cell = _dict(route_access.get("openedAccessCell"))
    if (
        route_access.get("followAvailable")
        and _to_int(opened_access_cell.get("x")) == _to_int(hole.get("x"))
        and _to_int(opened_access_cell.get("y")) == _to_int(hole.get("y"))
    ):
        return
    signature = "_".join(
        str(hole.get(field, "x")) for field in ("x", "y", "frameIndex", "frameTime")
    )
    add(
        kind="wait_for_floor_refill",
        key_code=STOP_KEYCODE,
        ticks=8,
        score=120,
        target={"x": hole.get("x"), "y": hole.get("y"), "tile": "#"},
        reason=(
            f"open dug brick at ({hole.get('x')},{hole.get('y')}) blocks safe {direction} "
            f"{'exit' if analysis.get('goldComplete') else 'gold'} progress; "
            f"refill frame {hole.get('frameIndex')} time {hole.get('frameTime')}"
        ),
        candidate_id=f"wait_for_floor_refill_{signature}",
    )


def add_descent_candidates(add, analysis: dict[str, Any], movement: dict[str, Any]) -> None:
    runner = analysis["runner"]
    runner_y = _to_int(runner.get("y"))
    lower_gold = [
        item
        for item in analysis["nearestGold"]
        if item.get("source") != "guard"
        and runner_y is not None
        and _to_int(item.get("y")) is not None
        and int(item["y"]) > runner_y
    ]
    if not lower_gold:
        return
    same_column_target = next(
        (item for item in lower_gold if item.get("direction") == "same"), None
    )
    if same_column_target and runner.get("action") == "fall":
        add(
            kind="descend_route",
            key_code=STOP_KEYCODE,
            ticks=8,
            score=116,
            target={"x": same_column_target["x"], "y": same_column_target["y"], "tile": "$"},
            reason="runner is already falling in the target gold column",
        )
    elif same_column_target and movement.get("currentTile") == "-":
        add(
            kind="descend_route",
            key_code=DOWN_KEYCODE,
            ticks=8,
            score=114,
            target={"x": same_column_target["x"], "y": same_column_target["y"], "tile": "$"},
            reason="runner is on rope above the target gold column",
        )
    if movement.get("canMoveDown"):
        target = lower_gold[0]
        add(
            kind="descend_route",
            key_code=DOWN_KEYCODE,
            ticks=8,
            score=110 if target.get("direction") == "same" else 86,
            target={"x": target["x"], "y": target["y"], "tile": "$"},
            reason="down movement is valid and remaining gold is below",
        )


def add_god_mode_progress_candidate(add, analysis: dict[str, Any]) -> None:
    movement = analysis["movement"]
    for target in [*analysis["nearestGold"], *analysis["rowLadders"]]:
        if target.get("source") == "guard":
            continue
        direction = target.get("direction")
        if direction not in {"left", "right"}:
            continue
        key_code = LEFT_KEYCODE if direction == "left" else RIGHT_KEYCODE
        if not movement.get("canMoveLeft" if direction == "left" else "canMoveRight"):
            continue
        tile = target.get("tile", "$")
        add(
            kind="god_mode_progress",
            key_code=key_code,
            ticks=8,
            score=72 if analysis.get("loopReport", {}).get("active") else 82,
            target={"x": target["x"], "y": target["y"], "tile": tile},
            reason="god mode is active; progress outranks survival spacing",
        )
        return


def add_low_risk_horizontal_progress_candidate(add, analysis: dict[str, Any]) -> None:
    target = _dict(analysis.get("primaryProgressTarget"))
    direction = target.get("direction")
    if direction not in {"left", "right"}:
        return
    movement = _dict(analysis.get("movement"))
    if not movement.get("canMoveLeft" if direction == "left" else "canMoveRight"):
        return
    add(
        kind="low_risk_horizontal_progress",
        key_code=LEFT_KEYCODE if direction == "left" else RIGHT_KEYCODE,
        ticks=4,
        score=70,
        target={"x": target.get("x"), "y": target.get("y"), "tile": target.get("tile", "$")},
        reason=(
            f"no structured route is available under low guard risk; move {direction} "
            "briefly toward the remaining gold and reassess"
        ),
    )


def add_wait_candidate(add) -> None:
    add(
        kind="wait_or_stop",
        key_code=STOP_KEYCODE,
        ticks=2,
        score=1,
        reason="fallback candidate",
        candidate_id="wait_or_stop",
    )


def add_emergency_hold_candidate(add, risk: dict[str, Any]) -> None:
    guard = _dict(risk.get("pressureGuard"))
    relative_y = guard.get("relativeY")
    signature = "_".join(
        str(guard.get(key, "unknown"))
        for key in ("id", "x", "y", "xOffset", "yOffset", "motion")
    )
    add(
        kind="emergency_hold",
        key_code=STOP_KEYCODE,
        ticks=2,
        score=0,
        reason=(
            f"all ordinary actions are filtered while the pressure guard is {relative_y}"
            if relative_y in {"above", "below"}
            else "no physically valid guard-safe action remains; use a bounded emergency hold"
        ),
        candidate_id=f"emergency_hold_{signature}",
    )


def choose_ladder_direction(snapshot: dict[str, Any], analysis: dict[str, Any]) -> str:
    runner_x = _to_int(analysis["runner"].get("x"))
    runner_y = _to_int(analysis["runner"].get("y")) or 0
    if bool(analysis["goldComplete"]):
        return "up"
    gold = _dict(analysis.get("gold"))
    if (
        gold.get("carriedByGuards")
        and not gold.get("visiblePositions")
        and runner_x == 7
        and _dict(analysis.get("movement")).get("canMoveDown")
    ):
        return "down"
    target = _dict(analysis.get("primaryProgressTarget"))
    target_y = _to_int(target.get("y"))
    if (
        _to_int(target.get("x")) == 4
        and target_y == 6
        and runner_x == 14
        and 4 <= runner_y <= 6
        and _dict(analysis.get("movement")).get("canMoveUp")
    ):
        return "up"
    if target_y is not None:
        if target_y < runner_y:
            return "up"
        if target_y > runner_y:
            return "down"
    return "up" if runner_y > 0 else "down"


def find_primary_progress_target(nearest_gold: list[dict[str, Any]]) -> dict[str, Any] | None:
    for gold in nearest_gold:
        if gold.get("source") == "guard":
            continue
        return {
            "x": gold.get("x"),
            "y": gold.get("y"),
            "tile": "$",
            "source": gold.get("source", "visible"),
            "sameRow": gold.get("sameRow"),
            "distance": gold.get("distance"),
            "direction": gold.get("direction"),
        }
    return None


def ladder_direction_toward_target(analysis: dict[str, Any], direction: str) -> bool:
    runner_y = _to_int(analysis["runner"].get("y"))
    target_y = _to_int(_dict(analysis.get("primaryProgressTarget")).get("y"))
    if runner_y is None or target_y is None:
        return False
    return (direction == "up" and target_y < runner_y) or (direction == "down" and target_y > runner_y)


def ladder_reason(ladder: dict[str, Any], direction: str, target: dict[str, Any]) -> str:
    if target:
        return (
            f"{ladder.get('detail', 'runner is on a ladder')} "
            f"Climb {direction} toward visible gold at ({target.get('x')},{target.get('y')})."
        )
    return str(ladder.get("detail", "runner is on a ladder"))


def ticks_for_alignment(distance: int) -> int:
    if distance <= 1:
        return 4
    if distance == 2:
        return 6
    return 8


def ticks_for_exit_alignment(runner_x: int | None, target_x: int | None) -> int:
    if runner_x is None or target_x is None:
        return 4
    return min(20, max(4, abs(target_x - runner_x) * 4))


def make_candidate_id(kind: str, target: dict[str, Any] | None, action_name: str) -> str:
    if target:
        x = target.get("x")
        y = target.get("y")
        if x is not None and y is not None:
            return f"{kind}_{x}_{y}_{action_name}"
    return f"{kind}_{action_name}"


def _trap_hole_between_pressure_guard(
    movement: dict[str, Any], risk: dict[str, Any]
) -> dict[str, Any]:
    guard = _dict(risk.get("pressureGuard"))
    side = guard.get("relativeX")
    if side not in {"left", "right"} or guard.get("relativeY") != "same":
        return {}
    if guard.get("motion") in {"up", "climb_out"}:
        return {}
    detail = _dict(_dict(movement.get("details")).get(side))
    hole = _dict(detail.get("openHole"))
    if hole.get("occupiedByTrappedGuard"):
        return {}
    distance = _to_int(hole.get("distance"))
    guard_x = _to_int(guard.get("x"))
    hole_x = _to_int(hole.get("x"))
    if distance not in {1, 2} or guard_x is None or hole_x is None:
        return {}
    guard_beyond_hole = guard_x <= hole_x if side == "left" else guard_x >= hole_x
    if not guard_beyond_hole:
        return {}
    return {"side": side, "hole": hole, "guard": guard}


def is_action_physically_valid(
    action: dict[str, Any],
    movement: dict[str, Any],
    dig: dict[str, Any],
    *,
    candidate_kind: str | None = None,
    runner_x_offset: int | None = None,
) -> bool:
    key_code = action.get("keyCode")
    if key_code == STOP_KEYCODE:
        return True
    if key_code == LEFT_KEYCODE:
        if _action_reaches_open_hole(
            action,
            movement,
            "left",
            candidate_kind,
            runner_x_offset=runner_x_offset,
        ):
            return False
        return bool(movement.get("canMoveLeft"))
    if key_code == RIGHT_KEYCODE:
        if _action_reaches_open_hole(
            action,
            movement,
            "right",
            candidate_kind,
            runner_x_offset=runner_x_offset,
        ):
            return False
        return bool(movement.get("canMoveRight"))
    if key_code == UP_KEYCODE:
        return bool(movement.get("canMoveUp")) or bool(
            candidate_kind == "exit_ladder_route" and movement.get("canFinishExitClimb")
        ) or bool(
            candidate_kind == "collect_current_tile_gold"
            and movement.get("canFinishLadderClimb")
        )
    if key_code == DOWN_KEYCODE:
        return bool(movement.get("canMoveDown"))
    if key_code == DIG_LEFT_KEYCODE:
        return bool(dig.get("canDigLeft")) or bool(
            candidate_kind == "defensive_dig"
            and _dict(dig.get("left")).get("canDefensiveDig")
            and _dict(dig.get("left")).get("guardCouldFall")
        )
    if key_code == DIG_RIGHT_KEYCODE:
        return bool(dig.get("canDigRight")) or bool(
            candidate_kind == "defensive_dig"
            and _dict(dig.get("right")).get("canDefensiveDig")
            and _dict(dig.get("right")).get("guardCouldFall")
        )
    return False


def limit_horizontal_ticks_before_open_hole(
    action: dict[str, Any], movement: dict[str, Any], candidate_kind: str
) -> dict[str, Any]:
    if candidate_kind in {
        "route_access_follow",
        "collect_current_tile_gold",
        "escape_through_open_hole",
    }:
        return action
    key_code = action.get("keyCode")
    direction = "left" if key_code == LEFT_KEYCODE else "right" if key_code == RIGHT_KEYCODE else None
    if direction is None:
        return action
    detail = _dict(_dict(movement.get("details")).get(direction))
    distance = _to_int(detail.get("openDugHoleDistance"))
    if distance is None:
        open_hole = _dict(detail.get("openHole"))
        if not open_hole.get("occupiedByTrappedGuard"):
            distance = _to_int(open_hole.get("distance"))
    if distance is None or distance <= 1:
        return action
    safe_ticks = (distance - 1) * 4
    return {**action, "ticks": min(int(action.get("ticks") or 1), safe_ticks)}


def apply_prospective_horizontal_endpoint_safety(
    action: dict[str, Any],
    analysis: dict[str, Any],
    candidate_kind: str,
    *,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if analysis.get("godMode") or candidate_kind not in PROSPECTIVE_HORIZONTAL_KINDS:
        return action
    key_code = action.get("keyCode")
    if key_code not in {LEFT_KEYCODE, RIGHT_KEYCODE}:
        return action
    risk = _dict(analysis.get("risk"))
    guard = _dict(risk.get("pressureGuard"))
    if guard.get("risk") not in GUARD_PRESSURE_RISKS or not guard.get("closing"):
        return action
    direction = "left" if key_code == LEFT_KEYCODE else "right"
    guard_behind = (
        guard.get("relativeX") == "right"
        if direction == "left"
        else guard.get("relativeX") == "left"
    )
    if not guard_behind:
        return action

    runner = _dict(analysis.get("runner"))
    runner_x = _to_int(runner.get("x"))
    x_offset = _to_int(runner.get("xOffset")) or 0
    edge_position_ahead = bool(
        runner_x is not None
        and (
            (direction == "left" and runner_x <= 1)
            or (direction == "right" and runner_x >= CLASSIC_LEVEL_WIDTH - 2)
        )
    )
    edge_vertical_escape = False
    if edge_position_ahead and snapshot is not None and runner_x is not None:
        projected_runner = {
            **_dict(snapshot.get("runner")),
            "x": runner_x - 1 if direction == "left" else runner_x + 1,
            "xOffset": 0,
            "yOffset": 0,
            "actionName": "stop",
        }
        projected_movement = get_movement_affordance(
            {**snapshot, "runner": projected_runner}
        )
        edge_vertical_escape = bool(
            projected_movement.get("canMoveUp") or projected_movement.get("canMoveDown")
        )
    edge_ahead = edge_position_ahead and not edge_vertical_escape
    movement = _dict(analysis.get("movement"))
    detail = _dict(_dict(movement.get("details")).get(direction))
    hole = _dict(detail.get("openHole"))
    hole_distance = _to_int(hole.get("distance"))
    hole_y = _to_int(hole.get("y"))
    terrain_height = _to_int(movement.get("terrainHeight"))
    bottom_hole_ahead = bool(
        hole_distance is not None
        and hole_distance <= 2
        and not hole.get("occupiedByTrappedGuard")
        and hole_y is not None
        and terrain_height is not None
        and hole_y >= terrain_height - 1
    )
    if not (edge_ahead or bottom_hole_ahead):
        return action

    moving_toward_center = bool(
        (direction == "left" and x_offset > 0)
        or (direction == "right" and x_offset < 0)
    )
    if not moving_toward_center:
        return None
    centering_ticks = max(1, (abs(x_offset) + LEGACY_SUBTILE_STEP - 1) // LEGACY_SUBTILE_STEP)
    if centering_ticks >= int(action.get("ticks") or 1):
        return action
    obstacle = "bottom-row hole" if bottom_hole_ahead else "level edge"
    return {
        **action,
        "ticks": centering_ticks,
        "reason": (
            f"{action.get('reason', '')}; stop centered before the {obstacle} because a closing "
            "guard is behind"
        )[:500],
    }


def _action_reaches_open_hole(
    action: dict[str, Any],
    movement: dict[str, Any],
    direction: str,
    candidate_kind: str | None,
    *,
    runner_x_offset: int | None = None,
) -> bool:
    if candidate_kind in {
        "route_access_follow",
        "collect_current_tile_gold",
        "escape_through_open_hole",
    }:
        return False
    detail = _dict(_dict(movement.get("details")).get(direction))
    distance = _to_int(detail.get("openDugHoleDistance"))
    if distance is None:
        open_hole = _dict(detail.get("openHole"))
        if not open_hole.get("occupiedByTrappedGuard"):
            distance = _to_int(open_hole.get("distance"))
    if distance is None:
        return False
    runner_x_offset = _to_int(runner_x_offset)
    moving_toward_center = bool(
        (direction == "left" and (runner_x_offset or 0) > 0)
        or (direction == "right" and (runner_x_offset or 0) < 0)
    )
    centering_ticks = (
        max(1, (abs(runner_x_offset) + LEGACY_SUBTILE_STEP - 1) // LEGACY_SUBTILE_STEP)
        if runner_x_offset
        else 0
    )
    if distance == 1 and moving_toward_center and int(action.get("ticks") or 1) <= centering_ticks:
        return False
    action_span = max(1, (int(action.get("ticks") or 1) + 3) // 4)
    return distance <= action_span


def is_action_guard_safe(
    action: dict[str, Any],
    analysis: dict[str, Any],
    *,
    candidate_kind: str | None = None,
) -> bool:
    if analysis.get("godMode"):
        return True
    risk = _dict(analysis.get("risk"))
    guard = _dict(risk.get("pressureGuard"))
    if guard.get("risk") not in GUARD_PRESSURE_RISKS:
        return True
    side = guard.get("relativeX")
    key_code = action.get("keyCode")
    if guard.get("risk") in {"high", "critical"} and side in {"left", "right"}:
        for nearby in risk.get("nearbyGuards") or []:
            nearby = _dict(nearby)
            nearby_side = nearby.get("relativeX")
            nearby_distance = _to_int(nearby.get("distance"))
            if (
                nearby.get("relativeY") == "same"
                and nearby_side in {"left", "right"}
                and nearby_side != side
                and nearby.get("closing")
                and nearby_distance is not None
                and nearby_distance <= 7
                and (
                    (nearby_side == "left" and key_code == LEFT_KEYCODE)
                    or (nearby_side == "right" and key_code == RIGHT_KEYCODE)
                )
            ):
                return False
    for nearby in risk.get("nearbyGuards") or []:
        nearby = _dict(nearby)
        if nearby.get("relativeY") != "same" or nearby.get("risk") not in GUARD_PRESSURE_RISKS:
            continue
        if nearby.get("relativeX") == "left" and key_code == LEFT_KEYCODE:
            return False
        if nearby.get("relativeX") == "right" and key_code == RIGHT_KEYCODE:
            return False
    if (
        candidate_kind == "evade_edge_ladder"
        and guard.get("relativeY") == "below"
        and key_code in {LEFT_KEYCODE, RIGHT_KEYCODE}
    ):
        return True
    if (
        candidate_kind == "evade_open_hole"
        and guard.get("relativeY") in {"above", "below"}
        and not guard.get("closing")
        and key_code in {LEFT_KEYCODE, RIGHT_KEYCODE}
    ):
        return True
    if (
        guard.get("risk") == "medium"
        and guard.get("relativeY") in {"above", "below"}
        and key_code in {LEFT_KEYCODE, RIGHT_KEYCODE}
    ):
        return True
    if side == "left" and key_code == LEFT_KEYCODE:
        return False
    if side == "right" and key_code == RIGHT_KEYCODE:
        return False
    relative_y = guard.get("relativeY")
    if (
        relative_y == "same"
        and guard.get("risk") in {"high", "critical"}
        and (_to_int(guard.get("distance")) or 0) <= 1
        and guard.get("motion") in {"up", "climb_out"}
        and key_code == UP_KEYCODE
    ):
        return False
    if candidate_kind == "emergency_hold" and key_code == STOP_KEYCODE:
        return True
    if (
        candidate_kind == "wait_for_dig_completion"
        and key_code == STOP_KEYCODE
        and _dict(analysis.get("activeDig")).get("active")
    ):
        return True
    if (
        candidate_kind == "wait_for_trap_resolution"
        and key_code == STOP_KEYCODE
        and _trap_hole_between_pressure_guard(
            _dict(analysis.get("movement")), risk
        )
    ):
        return True
    if relative_y == "above" and key_code == UP_KEYCODE:
        return False
    if relative_y == "below" and key_code == DOWN_KEYCODE:
        return False
    runner_action = _dict(analysis.get("runner")).get("action")
    if (
        guard.get("risk") in {"high", "critical"}
        and key_code == STOP_KEYCODE
        and runner_action != "fall"
    ):
        return False
    return True


def limit_horizontal_ticks_under_guard_pressure(
    action: dict[str, Any], analysis: dict[str, Any]
) -> dict[str, Any]:
    if analysis.get("godMode"):
        return action
    risk = _dict(analysis.get("risk"))
    guard = _dict(risk.get("pressureGuard"))
    if guard.get("risk") not in GUARD_PRESSURE_RISKS:
        return action
    if action.get("keyCode") not in {LEFT_KEYCODE, RIGHT_KEYCODE}:
        return action
    return {**action, "ticks": min(4, int(action.get("ticks") or 1))}


def _normalize_action(
    key_code: int,
    ticks: int,
    reason: str,
    *,
    max_ticks: int = AGENT_MAX_TICKS,
) -> dict[str, Any]:
    return {
        "keyCode": key_code,
        "ticks": max(1, min(max_ticks, int(ticks))),
        "reason": str(reason)[:500],
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
