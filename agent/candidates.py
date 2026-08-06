from __future__ import annotations

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
from .stall_tools import build_stall_report, score_adjustment


ACTION_NAMES = {
    STOP_KEYCODE: "stop",
    LEFT_KEYCODE: "left",
    RIGHT_KEYCODE: "right",
    UP_KEYCODE: "up",
    DOWN_KEYCODE: "down",
    DIG_LEFT_KEYCODE: "dig_left",
    DIG_RIGHT_KEYCODE: "dig_right",
}

GUARD_PRESSURE_RISKS = {"medium", "high", "critical"}

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
    9: 20,
    10: 20,
    11: 20,
}


def analyze_state(snapshot: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    runner = _dict(snapshot.get("runner"))
    gold = _dict(snapshot.get("gold"))
    guards = [_dict(item) for item in snapshot.get("guards") or [] if isinstance(item, dict)]
    nearest_gold = find_nearest_gold_candidates(snapshot, limit=5)
    row_ladders = find_row_ladders(snapshot, limit=6)
    primary_progress_target = find_primary_progress_target(nearest_gold)
    analysis = {
        "playData": snapshot.get("playData"),
        "level": snapshot.get("level"),
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
        "guards": [
            {
                "id": guard.get("id"),
                "x": guard.get("x"),
                "y": guard.get("y"),
                "action": guard.get("actionName"),
                "hasGold": guard.get("hasGold"),
                "sameRowAsRunner": guard.get("sameRowAsRunner"),
            }
            for guard in guards[:6]
        ],
        "gold": {
            "remainingCount": gold.get("remainingCount"),
            "complete": gold.get("complete"),
            "visiblePositions": gold.get("visiblePositions", []),
            "carriedByGuards": gold.get("carriedByGuards", []),
        },
        "nearestGold": nearest_gold,
        "primaryProgressTarget": primary_progress_target,
        "rowLadders": row_ladders,
        "risk": assess_guard_risk(snapshot),
        "movement": get_movement_affordance(snapshot),
        "dig": get_dig_affordance(snapshot),
        "ladder": get_ladder_affordance(snapshot),
        "routeAccess": get_route_access_affordance(snapshot),
        "activeDig": _dict(snapshot.get("activeDig")),
        "historyTail": history[-6:],
    }
    analysis["stallReport"] = build_stall_report(analysis, history)
    analysis["progressMonitor"] = analysis["stallReport"]
    return analysis


def generate_candidates(
    snapshot: dict[str, Any],
    history: list[dict[str, Any]],
    *,
    limit: int = 7,
    max_action_ticks: int = AGENT_MAX_TICKS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    analysis = analyze_state(snapshot, history)
    movement = analysis["movement"]
    dig = analysis["dig"]
    ladder = analysis["ladder"]
    route_access = analysis["routeAccess"]
    stall_report = analysis["stallReport"]
    risk = analysis["risk"]
    god_mode = bool(analysis["godMode"])
    guard_pressure = not god_mode and risk.get("risk") in GUARD_PRESSURE_RISKS
    gold_complete = bool(analysis["goldComplete"])
    runner = analysis["runner"]
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(
        *,
        kind: str,
        label: str,
        goal: str,
        key_code: int,
        ticks: int,
        score: int,
        target: dict[str, Any] | None = None,
        reason: str,
        preconditions: list[str] | None = None,
        stop_conditions: list[str] | None = None,
        candidate_id: str | None = None,
    ) -> None:
        action = _normalize_action(key_code, ticks, reason, max_ticks=max_action_ticks)
        action = limit_horizontal_ticks_under_guard_pressure(action, analysis)
        action = limit_horizontal_ticks_before_open_hole(action, movement, kind)
        if not is_action_physically_valid(action, movement, dig, candidate_kind=kind):
            return
        if not is_action_guard_safe(action, analysis, candidate_kind=kind):
            return
        cid = candidate_id or make_candidate_id(kind, target, ACTION_NAMES[key_code])
        if cid in seen:
            return
        seen.add(cid)
        adjustment, stall_meta = score_adjustment(
            {"id": cid, "kind": kind, "firstAction": action}, stall_report
        )
        candidates.append(
            {
                "id": cid,
                "kind": kind,
                "label": label,
                "goal": goal,
                "target": target,
                "firstAction": action,
                "preconditions": preconditions or [],
                "stopConditions": stop_conditions
                or ["state changes", "candidate preconditions become false", "terminal state reached"],
                "score": score + adjustment,
                "baseScore": score,
                "risk": risk.get("risk"),
                "reason": reason,
                **stall_meta,
            }
        )

    add_dig_completion_wait_candidate(add, analysis)
    if _dict(analysis.get("activeDig")).get("active"):
        candidates.sort(key=lambda item: (-int(item["score"]), item["id"]))
        return candidates[:limit], analysis
    add_floor_refill_wait_candidate(add, analysis)
    if add_trap_resolution_wait_candidate(add, movement, risk):
        candidates.sort(key=lambda item: (-int(item["score"]), item["id"]))
        return candidates[:limit], analysis

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
            label=f"Climb {direction} on current ladder",
            goal=f"Change rows using current ladder at ({runner_x},{runner_y})",
            key_code=UP_KEYCODE if direction == "up" else DOWN_KEYCODE,
            ticks=6,
            score=(
                122
                if direction_toward_target and stall_report.get("type") == "vertical_ladder_oscillation"
                else 108
                if direction_toward_target
                else 112
                if stall_report.get("stalled")
                else 95
                if not gold_complete
                else 105
            ),
            target={"x": runner_x, "y": runner_y, "tile": "S" if ladder.get("onExitLadder") else "H"},
            reason=ladder_reason(ladder, direction, target),
            preconditions=["runner is on active ladder"],
            stop_conditions=["runner changes row", "ladder no longer active", "terminal state reached"],
        )

    if not gold_complete:
        add_classic_upper_gold_route_candidate(add, analysis)
        add_classic_lower_gold_route_candidate(add, analysis)
        add_gold_candidates(add, analysis, god_mode)
        add_continue_fall_candidate(add, analysis, movement)
        add_ladder_alignment_candidates(add, analysis, god_mode)
        add_route_access_candidate(add, route_access, stall_report)
        add_route_access_follow_candidate(add, analysis, route_access)
        add_guard_clearance_wait_candidate(add, route_access)
        add_descent_candidate(add, analysis, movement)
    else:
        add_ladder_alignment_candidates(add, analysis, god_mode)

    if god_mode and not gold_complete:
        add_god_mode_progress_candidate(add, analysis)

    if not candidates or not (guard_pressure or stall_report.get("severity") == "stalled"):
        add_wait_candidate(add)

    if not candidates and guard_pressure:
        add_cross_row_pressure_hold_candidate(add, risk)

    if not candidates:
        add_emergency_hold_candidate(add, risk)

    candidates.sort(key=lambda item: (-int(item["score"]), item["id"]))
    return candidates[:limit], analysis


def add_exit_candidates(add, analysis: dict[str, Any], movement: dict[str, Any]) -> None:
    ladder = analysis["ladder"]
    runner = analysis["runner"]
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    if movement.get("canFinishExitClimb"):
        add(
            kind="finish_exit_climb",
            label="Finish the top exit climb",
            goal="Clear the final sub-tile offset at the top of the revealed exit ladder.",
            key_code=UP_KEYCODE,
            ticks=4,
            score=150,
            target={"x": 18, "y": 0, "tile": "S"},
            reason="runner is at (18,0) but remains below exit center by a positive yOffset",
            preconditions=["goldComplete=true", "runner=(18,0)", "runner.yOffset>0"],
            stop_conditions=["game reaches finish", "runner clears exit offset"],
        )
        return
    if ladder.get("onExitLadder"):
        add(
            kind="exit_ladder_route",
            label="Climb revealed exit ladder",
            goal="All gold is collected; climb the revealed `S` exit ladder.",
            key_code=UP_KEYCODE,
            ticks=ticks_for_exit_alignment(runner_x, _to_int(ladder_item.get("x"))),
            score=130,
            target={"x": runner_x, "y": runner_y, "tile": "S"},
            reason="runner is already on the revealed exit ladder",
            preconditions=["goldComplete=true", "runner is on `S`"],
            stop_conditions=["runner exits", "runner leaves exit ladder", "terminal state reached"],
        )
        return
    for ladder_item in analysis["rowLadders"]:
        if ladder_item.get("tile") != "S":
            continue
        direction = ladder_item.get("direction")
        key_code = LEFT_KEYCODE if direction == "left" else RIGHT_KEYCODE if direction == "right" else UP_KEYCODE
        add(
            kind="exit_ladder_route",
            label=f"Move {direction} to revealed exit ladder",
            goal=f"Align with revealed exit ladder at ({ladder_item['x']},{ladder_item['y']}).",
            key_code=key_code,
            ticks=20,
            score=125,
            target={"x": ladder_item["x"], "y": ladder_item["y"], "tile": "S"},
            reason="gold is complete and revealed exit ladder is on the runner row",
            preconditions=["goldComplete=true", "exit ladder is on runner row"],
            stop_conditions=["runner reaches exit ladder x", "route becomes blocked", "terminal state reached"],
        )
        return
    if movement.get("canMoveUp"):
        add(
            kind="exit_ladder_route",
            label="Climb toward exit",
            goal="All gold is collected; climb upward looking for the exit route.",
            key_code=UP_KEYCODE,
            ticks=20,
            score=115,
            target={"x": runner_x, "y": runner_y},
            reason="gold is complete and upward movement is valid",
            preconditions=["goldComplete=true", "canMoveUp=true"],
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
                label=f"Move {direction} to Classic exit waypoint ({waypoint_x},{runner_y})",
                goal="All gold is collected; follow the fixed Classic level-1 ladder chain toward the exit.",
                key_code=LEFT_KEYCODE if direction == "left" else RIGHT_KEYCODE,
                ticks=ticks_for_exit_alignment(runner_x, waypoint_x),
                score=132,
                target={"x": waypoint_x, "y": runner_y, "tile": exit_waypoint.get("tile")},
                reason=f"Classic level-1 exit chain uses x={waypoint_x} from row {runner_y}",
                preconditions=[
                    "goldComplete=true",
                    f"runner row is {runner_y}",
                    f"exit waypoint ({waypoint_x},{runner_y}) is visible",
                ],
                stop_conditions=[
                    f"runner reaches ladder x={waypoint_x}",
                    "route becomes blocked",
                    "terminal state reached",
                ],
                candidate_id=f"exit_ladder_route_{waypoint_x}_{runner_y}_{direction}",
            )


def add_classic_upper_gold_route_candidate(add, analysis: dict[str, Any]) -> None:
    target = _dict(analysis.get("primaryProgressTarget"))
    if _to_int(target.get("x")) != 23 or _to_int(target.get("y")) != 3:
        return
    runner = _dict(analysis.get("runner"))
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    if runner_x is None or runner_y is None or runner_y <= 3:
        return
    waypoint_x = CLASSIC_EXIT_ROW_WAYPOINTS.get(runner_y)
    if waypoint_x is None or runner_x == waypoint_x:
        return
    waypoint = next(
        (
            item
            for item in analysis.get("rowLadders") or []
            if _to_int(item.get("x")) == waypoint_x and _to_int(item.get("y")) == runner_y
        ),
        None,
    )
    if not waypoint:
        return
    direction = "left" if waypoint_x < runner_x else "right"
    add(
        kind="classic_upper_gold_route",
        label=f"Route {direction} to upper-gold waypoint ({waypoint_x},{runner_y})",
        goal="Use the fixed Classic ladder chain through x=20 and x=25 to reach gold at (23,3).",
        key_code=LEFT_KEYCODE if direction == "left" else RIGHT_KEYCODE,
        ticks=8,
        score=130,
        target={"x": waypoint_x, "y": runner_y, "tile": waypoint.get("tile")},
        reason=(
            f"Classic level-1 upper gold at (23,3) is reached through ladder x={waypoint_x} "
            f"from row {runner_y}"
        ),
        preconditions=["remaining visible gold target is (23,3)"],
        stop_conditions=["runner reaches waypoint ladder", "guard pressure changes", "terminal state reached"],
    )


def add_classic_lower_gold_route_candidate(add, analysis: dict[str, Any]) -> None:
    target = _dict(analysis.get("primaryProgressTarget"))
    target_x = _to_int(target.get("x"))
    target_y = _to_int(target.get("y"))
    if not target.get("visible", True):
        return
    runner = _dict(analysis.get("runner"))
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    if runner_x is None or runner_y is None:
        return
    if target_y == 14:
        waypoint_x = CLASSIC_LOWER_GOLD_ROW_WAYPOINTS.get(runner_y)
        route_goal = "Use the fixed Classic descent chain through x=25, x=20, and x=27 to reach row-14 gold."
        route_reason = "row-14 gold"
    elif target_x == 7 and target_y == 12:
        waypoint_x = CLASSIC_LEFT_GOLD_ROW_WAYPOINTS.get(runner_y)
        route_goal = "Use the x=20 descent ladder from rows 9–11 to reach left-side gold at (7,12)."
        route_reason = "left-side gold at (7,12)"
    else:
        return
    if waypoint_x is None or runner_x == waypoint_x:
        return
    direction = "left" if waypoint_x < runner_x else "right"
    add(
        kind="classic_lower_gold_route",
        label=f"Route {direction} to lower-gold waypoint ({waypoint_x},{runner_y})",
        goal=route_goal,
        key_code=LEFT_KEYCODE if direction == "left" else RIGHT_KEYCODE,
        ticks=8,
        score=132,
        target={"x": waypoint_x, "y": runner_y, "tile": "H"},
        reason=(
            f"Classic level-1 {route_reason} is reached through descent waypoint x={waypoint_x} "
            f"from row {runner_y}"
        ),
        preconditions=[f"primary visible gold target is ({target_x},{target_y})"],
        stop_conditions=["runner reaches descent waypoint", "guard pressure changes", "terminal state reached"],
    )


def add_non_god_escape_candidates(
    add,
    snapshot: dict[str, Any],
    movement: dict[str, Any],
    dig: dict[str, Any],
    risk: dict[str, Any],
) -> None:
    guard = (
        _dict(risk.get("pressureGuard"))
        or _dict(risk.get("nearestGuard"))
        or _dict(risk.get("nearestSameRowGuard"))
    )
    side = guard.get("side") or guard.get("relativeX")
    closing = bool(guard.get("closing"))
    guard_risk = guard.get("risk")
    left_dig = _dict(dig.get("left"))
    right_dig = _dict(dig.get("right"))
    active_trap = _trap_hole_between_pressure_guard(movement, risk)
    same_row_guards = [
        _dict(item) for item in risk.get("sameRowGuards") or [] if isinstance(item, dict)
    ]
    pinch = (
        any(item.get("side") == "left" and item.get("risk") in GUARD_PRESSURE_RISKS for item in same_row_guards)
        and any(item.get("side") == "right" and item.get("risk") in GUARD_PRESSURE_RISKS for item in same_row_guards)
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
            label=f"Step {edge_escape_direction} off climbing guard column",
            goal="Leave the edge ladder column before the cross-row guard climbs into it.",
            key_code=LEFT_KEYCODE if edge_escape_direction == "left" else RIGHT_KEYCODE,
            ticks=4,
            score=124,
            reason=(
                f"guard below is moving toward the edge ladder; step {edge_escape_direction} "
                "before it enters the runner's column"
            ),
            preconditions=["guard is below and approaching the edge ladder column"],
            stop_conditions=["runner leaves edge column", "guard geometry changes", "terminal state reached"],
            candidate_id=f"retreat_from_guard_edge_column_{edge_escape_direction}",
        )
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
            label=f"Step {hole_escape_direction} away from adjacent empty hole",
            goal="Preserve a solid escape side instead of digging a second adjacent hole.",
            key_code=RIGHT_KEYCODE if hole_escape_direction == "right" else LEFT_KEYCODE,
            ticks=4,
            score=124,
            reason=(
                f"adjacent empty hole blocks the opposite side; move {hole_escape_direction} "
                "while the cross-row guard is not closing"
            ),
            preconditions=["one adjacent floor is an empty open hole", "cross-row guard is not closing"],
            stop_conditions=["runner leaves the boxed column", "guard geometry changes", "terminal state reached"],
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
                    label=f"Drop {direction} through adjacent open hole",
                    goal="Break imminent guard contact by intentionally changing rows through the adjacent dug opening.",
                    key_code=key_code,
                    ticks=4,
                    score=126,
                    target={"x": hole.get("x"), "y": hole.get("y"), "tile": "open_hole"},
                    reason=f"{guard_risk} guard pressure leaves an adjacent open escape hole to the {direction}",
                    preconditions=[f"guard risk is {guard_risk}", f"adjacent {direction} floor is an open dug hole"],
                    stop_conditions=["runner begins falling", "runner changes row", "terminal state reached"],
                )
    if movement.get("canMoveUp"):
        add(
            kind="retreat_from_guard",
            label="Climb away from guard pressure",
            goal="Use current ladder to escape same-row guard danger.",
            key_code=UP_KEYCODE,
            ticks=6,
            score=120,
            reason="non-god-mode same-row guard pressure is active and up is valid",
            preconditions=["guard risk medium/high/critical", "canMoveUp=true"],
        )
    if movement.get("canMoveDown") and not edge_defensive_trap:
        add(
            kind="retreat_from_guard",
            label="Descend away from guard pressure",
            goal="Use current ladder descent to escape same-row guard danger.",
            key_code=DOWN_KEYCODE,
            ticks=6,
            score=118,
            reason="non-god-mode same-row guard pressure is active and down is valid",
            preconditions=["guard risk medium/high/critical", "canMoveDown=true"],
        )
    if side == "left" and left_dig_available and left_trap_ready:
        imminent_landing_trap = imminent_landing_side == "left"
        add(
            kind="defensive_dig",
            label="Dig left trap",
            goal="Trap or delay the approaching guard on the left.",
            key_code=DIG_LEFT_KEYCODE,
            ticks=8,
            score=136 if imminent_landing_trap else 134 if pinch else 132 if edge_defensive_trap else 112,
            reason=(
                "guard above-left is descending toward this row; dig_left now while centered"
                if imminent_landing_trap
                else "guard pressure from left and dig_left is legal"
            ),
            preconditions=["guard risk medium/high/critical", "canDigLeft=true"],
        )
    if side == "right" and right_dig_available and right_trap_ready:
        imminent_landing_trap = imminent_landing_side == "right"
        add(
            kind="defensive_dig",
            label="Dig right trap",
            goal="Trap or delay the approaching guard on the right.",
            key_code=DIG_RIGHT_KEYCODE,
            ticks=8,
            score=136 if imminent_landing_trap else 134 if pinch else 132 if edge_defensive_trap else 112,
            reason=(
                "guard above-right is descending toward this row; dig_right now while centered"
                if imminent_landing_trap
                else "guard pressure from right and dig_right is legal"
            ),
            preconditions=["guard risk medium/high/critical", "canDigRight=true"],
        )
    if side == "left" and movement.get("canMoveRight"):
        add(
            kind="retreat_from_guard",
            label="Reposition right from guard",
            goal="Move briefly away from the guard's current side, then reassess its position.",
            key_code=RIGHT_KEYCODE,
            ticks=6,
            score=108,
            reason=_guard_reposition_reason("left", "right", closing),
            preconditions=["guard risk medium/high/critical", "canMoveRight=true"],
            stop_conditions=["reassess guard position after this short move"],
        )
    if side == "right" and movement.get("canMoveLeft"):
        add(
            kind="retreat_from_guard",
            label="Reposition left from guard",
            goal="Move briefly away from the guard's current side, then reassess its position.",
            key_code=LEFT_KEYCODE,
            ticks=6,
            score=108,
            reason=_guard_reposition_reason("right", "left", closing),
            preconditions=["guard risk medium/high/critical", "canMoveLeft=true"],
            stop_conditions=["reassess guard position after this short move"],
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
                label=f"Break vertical alignment to the {direction}",
                goal="Move off the pressure guard's column, then reassess its route.",
                key_code=key_code,
                ticks=4,
                score=110,
                reason=f"guard is vertically aligned on another row; move {direction} to break its approach line",
                preconditions=["guard risk medium/high/critical", "guard is on runner column", f"{movement_key}=true"],
                stop_conditions=["runner leaves guard column", "guard relation changes", "terminal state reached"],
                candidate_id=f"retreat_from_guard_same_column_{direction}",
            )


def _guard_reposition_reason(guard_side: str, move_direction: str, closing: bool) -> str:
    motion = "closing" if closing else "not currently closing"
    return (
        f"guard is on the {guard_side} and {motion}; move {move_direction} briefly, "
        "then reassess because the guard may follow and distance may not increase"
    )


def add_gold_candidates(add, analysis: dict[str, Any], god_mode: bool) -> None:
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
            key_code = LEFT_KEYCODE if x_offset > 0 else RIGHT_KEYCODE if x_offset < 0 else STOP_KEYCODE
            ticks = min(4, max(2, (abs(x_offset) + 3) // 4)) if x_offset else 2
            add(
                kind="collect_current_tile_gold",
                label="Center on current-tile gold",
                goal=f"Collect gold already under the runner at ({gold['x']},{gold['y']}).",
                key_code=key_code,
                ticks=ticks,
                score=122,
                target={"x": gold["x"], "y": gold["y"], "tile": "$"},
                reason=(
                    f"gold shares the runner tile; center from xOffset {x_offset}"
                    if x_offset
                    else "gold shares the centered runner tile; advance collision processing"
                ),
                preconditions=["visible gold shares runner coordinates"],
                stop_conditions=["gold is collected", "terminal state reached"],
            )
            continue
        if direction not in {"left", "right"}:
            continue
        key_code = LEFT_KEYCODE if direction == "left" else RIGHT_KEYCODE
        if not movement.get("canMoveLeft" if direction == "left" else "canMoveRight"):
            continue
        add(
            kind="collect_same_row_gold",
            label=f"Move {direction} to gold",
            goal=f"Collect same-row gold at ({gold['x']},{gold['y']}).",
            key_code=key_code,
            ticks=8,
            score=106 if god_mode else 100,
            target={"x": gold["x"], "y": gold["y"], "tile": "$"},
            reason=f"same-row gold is {gold['distance']} tiles to the {direction}",
            preconditions=["goldComplete=false", "same-row gold exists", f"canMove{direction.title()}=true"],
            stop_conditions=["gold is collected", "route becomes blocked", "runner changes row", "terminal state reached"],
        )


def add_ladder_alignment_candidates(add, analysis: dict[str, Any], god_mode: bool) -> None:
    movement = analysis["movement"]
    progress_monitor = analysis["progressMonitor"]
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
        stalled_target = progress_monitor.get("oscillationTarget") == {
            "x": ladder.get("x"),
            "y": ladder.get("y"),
            "kind": "ladder",
        }
        add(
            kind="align_ladder",
            label=f"{'Fine-align' if fine_align else 'Move'} {direction} to ladder",
            goal=f"Align with visible ladder at ({ladder['x']},{ladder['y']}).",
            key_code=key_code,
            ticks=ticks_for_alignment(distance),
            score=ladder_alignment_score(
                distance,
                god_mode=god_mode,
                fine_align=fine_align,
                stalled_target=stalled_target,
            ),
            target={"x": ladder["x"], "y": ladder["y"], "tile": "H"},
            reason=f"visible ladder is {ladder['distance']} tiles to the {direction}",
            preconditions=[
                "visible ladder on runner row",
                f"canMove{direction.title()}=true",
                "anti-stall fine alignment" if fine_align else "ladder route progress",
            ],
            stop_conditions=[
                "runner reaches ladder x",
                "route becomes blocked",
                "terminal state reached",
            ],
        )


def ladder_alignment_score(
    distance: int, *, god_mode: bool, fine_align: bool, stalled_target: bool
) -> int:
    if stalled_target:
        return 118
    if fine_align:
        return 104
    base = 94 if god_mode else 90
    return base + max(0, 12 - min(max(distance, 0), 12))


def add_route_access_candidate(
    add, route_access: dict[str, Any], progress_monitor: dict[str, Any]
) -> None:
    if not route_access.get("available"):
        return
    action_name = route_access.get("recommendedAction")
    if action_name not in DIG_KEYCODES:
        return
    candidate_id = f"route_access_{action_name}"
    if progress_monitor.get("blockedCandidateId") == candidate_id:
        return
    off_row_gold = _dict(route_access.get("offRowGoldTarget"))
    add(
        kind="route_access_dig",
        label=action_name,
        goal=(
            f"Open a descent/access route toward lower gold at "
            f"({off_row_gold.get('x')},{off_row_gold.get('y')})."
        ),
        key_code=DIG_KEYCODES[action_name],
        ticks=12,
        score=88,
        target=off_row_gold,
        reason=str(route_access.get("reason", "legal route-access dig is available")),
        preconditions=["goldComplete=false", "no same-row gold/ladder route", "recommended dig is legal"],
        stop_conditions=["hole opens", "runner changes route/row", "dig becomes invalid", "terminal state reached"],
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
        label=f"Move {direction} into opened access route",
        goal=(
            f"Follow the opened access route at ({opened_cell.get('x')},{opened_cell.get('y')}) "
            f"toward lower gold at ({off_row_gold.get('x')},{off_row_gold.get('y')})."
        ),
        key_code=key_code,
        ticks=8,
        score=104,
        target=opened_cell or off_row_gold,
        reason=str(route_access.get("reason", "access route is open; move into it")),
        preconditions=["goldComplete=false", "route-access hole is already open"],
        stop_conditions=["runner enters access route", "runner falls/changes row", "terminal state reached"],
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
        label="Wait for access-route guard clearance",
        goal="Delay entry into the opened drop until converging guards clear its landing corridor.",
        key_code=STOP_KEYCODE,
        ticks=2,
        score=120,
        target=opened_cell,
        reason=str(route_access.get("reason", "guard blocks safe access-route entry")),
        preconditions=["access hole is open", "a guard can intercept the drop"],
        stop_conditions=["drop corridor clears", "guard reaches runner row", "terminal state reached"],
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
        label="Finish active defensive dig",
        goal="Advance the legacy dig animation until the trap brick opens.",
        key_code=STOP_KEYCODE,
        ticks=2,
        score=142,
        target=target,
        reason=(
            f"legacy dig at ({target['x']},{target['y']}) is still active "
            f"at frame {frame_index}/{frame_count}"
        ),
        preconditions=["activeDig.active=true"],
        stop_conditions=["dig completes", "hole opens", "terminal state reached"],
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
        label="Hold behind active guard trap",
        goal="Let the existing dug hole trap or redirect the separated pressure guard.",
        key_code=STOP_KEYCODE,
        ticks=wait_ticks,
        score=140,
        target={"x": hole.get("x"), "y": hole.get("y"), "tile": "open_hole"},
        reason=(
            f"open hole at ({hole.get('x')},{hole.get('y')}) already separates "
            f"the {trap.get('side')}-side pressure guard"
        ),
        preconditions=["pressure guard is separated by an existing open hole"],
        stop_conditions=["guard falls or changes geometry", "hole state changes", "terminal state reached"],
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
    signature = "_".join(
        str(hole.get(field, "x")) for field in ("x", "y", "frameIndex", "frameTime")
    )
    add(
        kind="wait_for_floor_refill",
        label="Wait for dug floor to refill",
        goal="Hold on the safe side of the open brick until its timed refill completes.",
        key_code=STOP_KEYCODE,
        ticks=8,
        score=120,
        target={"x": hole.get("x"), "y": hole.get("y"), "tile": "#"},
        reason=(
            f"open dug brick at ({hole.get('x')},{hole.get('y')}) blocks safe {direction} "
            f"{'exit' if analysis.get('goldComplete') else 'gold'} progress; "
            f"refill frame {hole.get('frameIndex')} time {hole.get('frameTime')}"
        ),
        preconditions=["required horizontal route crosses an open dug brick"],
        stop_conditions=["brick refills", "guard pressure changes", "terminal state reached"],
        candidate_id=f"wait_for_floor_refill_{signature}",
    )


def add_descent_candidate(add, analysis: dict[str, Any], movement: dict[str, Any]) -> None:
    if not movement.get("canMoveDown"):
        return
    runner_y = _to_int(analysis["runner"].get("y"))
    lower_gold = [
        item
        for item in analysis["nearestGold"]
        if runner_y is not None and _to_int(item.get("y")) is not None and int(item["y"]) > runner_y
    ]
    if not lower_gold:
        return
    target = lower_gold[0]
    same_column = target.get("direction") == "same"
    add(
        kind="descend_route",
        label="Move down toward lower gold",
        goal=f"Descend toward lower remaining gold at ({target['x']},{target['y']}).",
        key_code=DOWN_KEYCODE,
        ticks=8,
        score=110 if same_column else 86,
        target={"x": target["x"], "y": target["y"], "tile": "$"},
        reason="down movement is valid and remaining gold is below",
        preconditions=["canMoveDown=true", "remaining gold is below"],
        stop_conditions=["runner changes row", "down becomes invalid", "terminal state reached"],
    )


def add_continue_fall_candidate(add, analysis: dict[str, Any], movement: dict[str, Any]) -> None:
    runner = analysis["runner"]
    runner_y = _to_int(runner.get("y"))
    runner_action = runner.get("action")
    current_tile = movement.get("currentTile")
    lower_gold = [
        item
        for item in analysis["nearestGold"]
        if (
            runner_y is not None
            and _to_int(item.get("y")) is not None
            and int(item["y"]) > runner_y
            and item.get("direction") == "same"
        )
    ]
    if not lower_gold:
        return
    target = lower_gold[0]
    if runner_action == "fall":
        add(
            kind="continue_fall",
            label="Continue falling toward lower gold",
            goal=f"Keep falling in the same column toward gold at ({target['x']},{target['y']}).",
            key_code=STOP_KEYCODE,
            ticks=8,
            score=116,
            target={"x": target["x"], "y": target["y"], "tile": "$"},
            reason="runner is already falling in the target gold column",
            preconditions=["runner action is fall", "remaining gold is below in same column"],
            stop_conditions=["runner lands", "runner changes row/route", "terminal state reached"],
        )
    elif current_tile == "-":
        add(
            kind="continue_fall",
            label="Drop from rope toward lower gold",
            goal=f"Drop from the rope toward gold at ({target['x']},{target['y']}).",
            key_code=DOWN_KEYCODE,
            ticks=8,
            score=114,
            target={"x": target["x"], "y": target["y"], "tile": "$"},
            reason="runner is on rope above the target gold column",
            preconditions=["runner is on rope", "remaining gold is below in same column"],
            stop_conditions=["runner begins falling", "runner changes row/route", "terminal state reached"],
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
            kind="godmode_progress",
            label=f"God-mode progress {direction}",
            goal=f"Use non-lethal guard contact if needed to progress toward ({target['x']},{target['y']}).",
            key_code=key_code,
            ticks=8,
            score=72 if analysis.get("progressMonitor", {}).get("stalled") else 82,
            target={"x": target["x"], "y": target["y"], "tile": tile},
            reason="god mode is active; progress outranks survival spacing",
            preconditions=["godMode=true", f"canMove{direction.title()}=true"],
            stop_conditions=["target reached", "route becomes physically blocked", "terminal state reached"],
        )
        return


def add_wait_candidate(add) -> None:
    add(
        kind="wait_or_stop",
        label="Stop briefly",
        goal="Wait only if no progress or safety candidate is better.",
        key_code=STOP_KEYCODE,
        ticks=2,
        score=1,
        reason="fallback candidate",
        preconditions=[],
        stop_conditions=["next snapshot is available"],
        candidate_id="wait_or_stop",
    )


def add_cross_row_pressure_hold_candidate(add, risk: dict[str, Any]) -> None:
    guard = (
        _dict(risk.get("pressureGuard"))
        or _dict(risk.get("nearestGuard"))
        or _dict(risk.get("nearestSameRowGuard"))
    )
    relative_y = guard.get("relativeY")
    if relative_y not in {"above", "below"}:
        return
    signature = "_".join(
        str(guard.get(key, "unknown"))
        for key in ("id", "x", "y", "xOffset", "yOffset", "motion")
    )
    add(
        kind="cross_row_pressure_hold",
        label="Hold while cross-row guard passes",
        goal="Preserve a safe separated-row position until guard geometry changes.",
        key_code=STOP_KEYCODE,
        ticks=2,
        score=80,
        reason=f"all ordinary actions are filtered while the pressure guard is {relative_y}",
        preconditions=["guard is on another row", "no ordinary candidate is valid"],
        stop_conditions=["guard geometry changes", "an ordinary candidate becomes valid"],
        candidate_id=f"cross_row_pressure_hold_{signature}",
    )


def add_emergency_hold_candidate(add, risk: dict[str, Any]) -> None:
    guard = _dict(risk.get("pressureGuard") or risk.get("nearestGuard"))
    signature = "_".join(
        str(guard.get(key, "unknown"))
        for key in ("id", "x", "y", "xOffset", "yOffset", "motion")
    )
    add(
        kind="emergency_hold",
        label="Hold through fully blocked contact",
        goal="Advance the legacy engine when every movement, dig, and ordinary wait is filtered.",
        key_code=STOP_KEYCODE,
        ticks=2,
        score=0,
        reason="no physically valid guard-safe action remains; use a bounded emergency hold",
        preconditions=["candidate set would otherwise be empty"],
        stop_conditions=["guard geometry changes", "a physical action becomes valid", "terminal state reached"],
        candidate_id=f"emergency_hold_{signature}",
    )


def choose_ladder_direction(snapshot: dict[str, Any], analysis: dict[str, Any]) -> str:
    runner_y = _to_int(analysis["runner"].get("y")) or 0
    if bool(analysis["goldComplete"]):
        return "up"
    target = _dict(analysis.get("primaryProgressTarget"))
    target_y = _to_int(target.get("y"))
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
    guard = (
        _dict(risk.get("pressureGuard"))
        or _dict(risk.get("nearestSameRowGuard"))
        or _dict(risk.get("nearestGuard"))
    )
    side = guard.get("side") or guard.get("relativeX")
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
) -> bool:
    key_code = action.get("keyCode")
    if key_code == STOP_KEYCODE:
        return True
    if key_code == LEFT_KEYCODE:
        if _action_reaches_open_hole(action, movement, "left", candidate_kind):
            return False
        return bool(movement.get("canMoveLeft"))
    if key_code == RIGHT_KEYCODE:
        if _action_reaches_open_hole(action, movement, "right", candidate_kind):
            return False
        return bool(movement.get("canMoveRight"))
    if key_code == UP_KEYCODE:
        return bool(movement.get("canMoveUp")) or bool(
            candidate_kind == "finish_exit_climb" and movement.get("canFinishExitClimb")
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


def _action_reaches_open_hole(
    action: dict[str, Any],
    movement: dict[str, Any],
    direction: str,
    candidate_kind: str | None,
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
    guard = (
        _dict(risk.get("pressureGuard"))
        or _dict(risk.get("nearestGuard"))
        or _dict(risk.get("nearestSameRowGuard"))
    )
    if guard.get("risk") not in GUARD_PRESSURE_RISKS:
        return True
    side = guard.get("side") or guard.get("relativeX")
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
        candidate_kind == "cross_row_pressure_hold"
        and relative_y in {"above", "below"}
        and key_code == STOP_KEYCODE
    ):
        return True
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
    guard = (
        _dict(risk.get("pressureGuard"))
        or _dict(risk.get("nearestGuard"))
        or _dict(risk.get("nearestSameRowGuard"))
    )
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
