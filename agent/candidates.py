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
    find_nearest_gold_candidates,
    find_row_ladders,
    get_dig_affordance,
    get_ladder_affordance,
    get_movement_affordance,
    get_route_access_affordance,
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

DIG_KEYCODES = {
    "dig_left": DIG_LEFT_KEYCODE,
    "dig_right": DIG_RIGHT_KEYCODE,
}


def analyze_state(snapshot: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    runner = _dict(snapshot.get("runner"))
    gold = _dict(snapshot.get("gold"))
    guards = [_dict(item) for item in snapshot.get("guards") or [] if isinstance(item, dict)]
    nearest_gold = find_nearest_gold_candidates(snapshot, limit=5)
    row_ladders = find_row_ladders(snapshot, limit=6)
    return {
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
        "rowLadders": row_ladders,
        "risk": assess_guard_risk(snapshot),
        "movement": get_movement_affordance(snapshot),
        "dig": get_dig_affordance(snapshot),
        "ladder": get_ladder_affordance(snapshot),
        "routeAccess": get_route_access_affordance(snapshot),
        "historyTail": history[-6:],
    }


def generate_candidates(
    snapshot: dict[str, Any],
    history: list[dict[str, Any]],
    *,
    limit: int = 7,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    analysis = analyze_state(snapshot, history)
    movement = analysis["movement"]
    dig = analysis["dig"]
    ladder = analysis["ladder"]
    route_access = analysis["routeAccess"]
    risk = analysis["risk"]
    god_mode = bool(analysis["godMode"])
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
        action = _normalize_action(key_code, ticks, reason)
        if not is_action_physically_valid(action, movement, dig):
            return
        cid = candidate_id or make_candidate_id(kind, target, ACTION_NAMES[key_code])
        if cid in seen:
            return
        seen.add(cid)
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
                "score": score,
                "risk": risk.get("risk"),
                "reason": reason,
            }
        )

    if gold_complete:
        add_exit_candidates(add, analysis, movement)

    if risk.get("risk") in {"critical", "high"} and not god_mode:
        add_non_god_escape_candidates(add, movement, dig, risk)

    if ladder.get("onLadder"):
        direction = choose_ladder_direction(snapshot, analysis)
        add(
            kind="climb_ladder",
            label=f"Climb {direction} on current ladder",
            goal=f"Change rows using current ladder at ({runner_x},{runner_y})",
            key_code=UP_KEYCODE if direction == "up" else DOWN_KEYCODE,
            ticks=8,
            score=95 if not gold_complete else 105,
            target={"x": runner_x, "y": runner_y, "tile": "S" if ladder.get("onExitLadder") else "H"},
            reason=ladder.get("detail", "runner is on a ladder"),
            preconditions=["runner is on active ladder"],
            stop_conditions=["runner changes row", "ladder no longer active", "terminal state reached"],
        )

    if not gold_complete:
        add_gold_candidates(add, analysis, god_mode)
        add_ladder_alignment_candidates(add, analysis, god_mode)
        add_route_access_candidate(add, route_access)
        add_descent_candidate(add, analysis, movement)

    if god_mode:
        add_god_mode_progress_candidate(add, analysis)

    add_wait_candidate(add)

    candidates.sort(key=lambda item: (-int(item["score"]), item["id"]))
    return candidates[:limit], analysis


def add_exit_candidates(add, analysis: dict[str, Any], movement: dict[str, Any]) -> None:
    ladder = analysis["ladder"]
    runner = analysis["runner"]
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    if ladder.get("onExitLadder"):
        add(
            kind="exit_ladder_route",
            label="Climb revealed exit ladder",
            goal="All gold is collected; climb the revealed `S` exit ladder.",
            key_code=UP_KEYCODE,
            ticks=8,
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
            ticks=8,
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
            ticks=8,
            score=115,
            target={"x": runner_x, "y": runner_y},
            reason="gold is complete and upward movement is valid",
            preconditions=["goldComplete=true", "canMoveUp=true"],
        )


def add_non_god_escape_candidates(add, movement: dict[str, Any], dig: dict[str, Any], risk: dict[str, Any]) -> None:
    guard = _dict(risk.get("nearestSameRowGuard"))
    direction = guard.get("direction")
    if movement.get("canMoveUp"):
        add(
            kind="retreat_from_guard",
            label="Climb away from guard pressure",
            goal="Use current ladder to escape same-row guard danger.",
            key_code=UP_KEYCODE,
            ticks=6,
            score=120,
            reason="non-god-mode guard pressure is high and up is valid",
            preconditions=["guard risk high/critical", "canMoveUp=true"],
        )
    if movement.get("canMoveDown"):
        add(
            kind="retreat_from_guard",
            label="Descend away from guard pressure",
            goal="Use current ladder descent to escape same-row guard danger.",
            key_code=DOWN_KEYCODE,
            ticks=6,
            score=118,
            reason="non-god-mode guard pressure is high and down is valid",
            preconditions=["guard risk high/critical", "canMoveDown=true"],
        )
    if direction == "left" and dig.get("canDigLeft"):
        add(
            kind="defensive_dig",
            label="Dig left trap",
            goal="Trap or delay the approaching guard on the left.",
            key_code=DIG_LEFT_KEYCODE,
            ticks=8,
            score=112,
            reason="guard pressure from left and dig_left is legal",
            preconditions=["guard risk high/critical", "canDigLeft=true"],
        )
    if direction == "right" and dig.get("canDigRight"):
        add(
            kind="defensive_dig",
            label="Dig right trap",
            goal="Trap or delay the approaching guard on the right.",
            key_code=DIG_RIGHT_KEYCODE,
            ticks=8,
            score=112,
            reason="guard pressure from right and dig_right is legal",
            preconditions=["guard risk high/critical", "canDigRight=true"],
        )
    if direction == "left" and movement.get("canMoveRight"):
        add(
            kind="retreat_from_guard",
            label="Move right away from guard",
            goal="Create safe distance from same-row guard on the left.",
            key_code=RIGHT_KEYCODE,
            ticks=6,
            score=108,
            reason="guard is left; moving right increases distance",
            preconditions=["guard risk high/critical", "canMoveRight=true"],
        )
    if direction == "right" and movement.get("canMoveLeft"):
        add(
            kind="retreat_from_guard",
            label="Move left away from guard",
            goal="Create safe distance from same-row guard on the right.",
            key_code=LEFT_KEYCODE,
            ticks=6,
            score=108,
            reason="guard is right; moving left increases distance",
            preconditions=["guard risk high/critical", "canMoveLeft=true"],
        )


def add_gold_candidates(add, analysis: dict[str, Any], god_mode: bool) -> None:
    movement = analysis["movement"]
    for gold in analysis["nearestGold"]:
        if not gold.get("sameRow"):
            continue
        direction = gold.get("direction")
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
    for ladder in analysis["rowLadders"]:
        if ladder.get("tile") != "H" or ladder.get("distance") == 0:
            continue
        direction = ladder.get("direction")
        if direction not in {"left", "right"}:
            continue
        key_code = LEFT_KEYCODE if direction == "left" else RIGHT_KEYCODE
        if not movement.get("canMoveLeft" if direction == "left" else "canMoveRight"):
            continue
        add(
            kind="align_ladder",
            label=f"Move {direction} to ladder",
            goal=f"Align with visible ladder at ({ladder['x']},{ladder['y']}).",
            key_code=key_code,
            ticks=8,
            score=94 if god_mode else 90,
            target={"x": ladder["x"], "y": ladder["y"], "tile": "H"},
            reason=f"visible ladder is {ladder['distance']} tiles to the {direction}",
            preconditions=["visible ladder on runner row", f"canMove{direction.title()}=true"],
            stop_conditions=["runner reaches ladder x", "route becomes blocked", "terminal state reached"],
        )


def add_route_access_candidate(add, route_access: dict[str, Any]) -> None:
    if not route_access.get("available"):
        return
    action_name = route_access.get("recommendedAction")
    if action_name not in DIG_KEYCODES:
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
        ticks=8,
        score=88,
        target=off_row_gold,
        reason=str(route_access.get("reason", "legal route-access dig is available")),
        preconditions=["goldComplete=false", "no same-row gold/ladder route", "recommended dig is legal"],
        stop_conditions=["hole opens", "runner changes route/row", "dig becomes invalid", "terminal state reached"],
        candidate_id=f"route_access_{action_name}",
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
    add(
        kind="descend_route",
        label="Move down toward lower gold",
        goal=f"Descend toward lower remaining gold at ({target['x']},{target['y']}).",
        key_code=DOWN_KEYCODE,
        ticks=8,
        score=86,
        target={"x": target["x"], "y": target["y"], "tile": "$"},
        reason="down movement is valid and remaining gold is below",
        preconditions=["canMoveDown=true", "remaining gold is below"],
        stop_conditions=["runner changes row", "down becomes invalid", "terminal state reached"],
    )


def add_god_mode_progress_candidate(add, analysis: dict[str, Any]) -> None:
    movement = analysis["movement"]
    for target in [*analysis["nearestGold"], *analysis["rowLadders"]]:
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
            score=82,
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


def choose_ladder_direction(snapshot: dict[str, Any], analysis: dict[str, Any]) -> str:
    runner_y = _to_int(analysis["runner"].get("y")) or 0
    runner_x = _to_int(analysis["runner"].get("x"))
    if bool(analysis["goldComplete"]):
        return "up"
    if runner_x is not None:
        for gold in analysis["nearestGold"]:
            if _to_int(gold.get("x")) == runner_x and (_to_int(gold.get("y")) or 0) > runner_y:
                return "down"
    return "up" if runner_y > 0 else "down"


def make_candidate_id(kind: str, target: dict[str, Any] | None, action_name: str) -> str:
    if target:
        x = target.get("x")
        y = target.get("y")
        if x is not None and y is not None:
            return f"{kind}_{x}_{y}_{action_name}"
    return f"{kind}_{action_name}"


def is_action_physically_valid(
    action: dict[str, Any], movement: dict[str, Any], dig: dict[str, Any]
) -> bool:
    key_code = action.get("keyCode")
    if key_code == STOP_KEYCODE:
        return True
    if key_code == LEFT_KEYCODE:
        return bool(movement.get("canMoveLeft"))
    if key_code == RIGHT_KEYCODE:
        return bool(movement.get("canMoveRight"))
    if key_code == UP_KEYCODE:
        return bool(movement.get("canMoveUp"))
    if key_code == DOWN_KEYCODE:
        return bool(movement.get("canMoveDown"))
    if key_code == DIG_LEFT_KEYCODE:
        return bool(dig.get("canDigLeft"))
    if key_code == DIG_RIGHT_KEYCODE:
        return bool(dig.get("canDigRight"))
    return False


def _normalize_action(key_code: int, ticks: int, reason: str) -> dict[str, Any]:
    return {
        "keyCode": key_code,
        "ticks": max(1, min(AGENT_MAX_TICKS, int(ticks))),
        "reason": str(reason)[:500],
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
