from __future__ import annotations

from collections import Counter
from typing import Any


LEFT_KEYCODE = 37
UP_KEYCODE = 38
RIGHT_KEYCODE = 39
DOWN_KEYCODE = 40
STOP_KEYCODE = 32
DIG_LEFT_KEYCODE = 90
DIG_RIGHT_KEYCODE = 88

HORIZONTAL_KEYCODES = {LEFT_KEYCODE: "left", RIGHT_KEYCODE: "right"}
VERTICAL_KEYCODES = {UP_KEYCODE: "up", DOWN_KEYCODE: "down"}
DIG_KEYCODES = {DIG_LEFT_KEYCODE: "dig_left", DIG_RIGHT_KEYCODE: "dig_right"}
BLOCKING_TILES = {"#", "@"}


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _get_runner(snapshot: dict[str, Any]) -> dict[str, Any]:
    runner = snapshot.get("runner") or {}
    return runner if isinstance(runner, dict) else {}


def _get_grid(snapshot: dict[str, Any], key: str) -> list[str]:
    rows = snapshot.get(key) or []
    if not isinstance(rows, list):
        return []
    return [row if isinstance(row, str) else str(row) for row in rows]


def _get_terrain_grid(snapshot: dict[str, Any]) -> list[str]:
    return _get_grid(snapshot, "terrainGrid")


def _is_gold_complete(snapshot: dict[str, Any]) -> bool:
    gold = snapshot.get("gold") or {}
    if isinstance(gold, dict) and "complete" in gold:
        return bool(gold.get("complete"))
    return bool(snapshot.get("goldComplete"))


def _active_ladder_tiles(snapshot: dict[str, Any]) -> set[str]:
    return {"H", "S"} if _is_gold_complete(snapshot) else {"H"}


def _get_gold_positions(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    gold = snapshot.get("gold") or {}
    visible_positions = gold.get("visiblePositions")
    if not isinstance(visible_positions, list):
        return []

    positions = []
    for item in visible_positions:
        if not isinstance(item, dict):
            continue
        x = _to_int(item.get("x"))
        y = _to_int(item.get("y"))
        if x is None or y is None:
            continue
        positions.append({"x": x, "y": y, "tile": "$"})
    return positions


def _grid_width(rows: list[str]) -> int:
    return max((len(row) for row in rows), default=0)


def _scan_positions(rows: list[str], targets: set[str]) -> list[dict[str, Any]]:
    positions: list[dict[str, Any]] = []
    for y, row in enumerate(rows):
        for x, char in enumerate(row):
            if char in targets:
                positions.append({"x": x, "y": y, "tile": char})
    return positions


def _direction_label(origin_x: int, target_x: int) -> str:
    if target_x < origin_x:
        return "left"
    if target_x > origin_x:
        return "right"
    return "same"


def _is_edge(x: int, width: int) -> bool:
    if width <= 0:
        return False
    return x <= 1 or x >= max(0, width - 2)


def _terrain_at(rows: list[str], x: int, y: int) -> str | None:
    if y < 0 or y >= len(rows):
        return None
    row = rows[y]
    if x < 0 or x >= len(row):
        return None
    return row[x]


def _display_tile(tile: str | None) -> str:
    if tile is None:
        return "out-of-bounds"
    return "." if tile == " " else tile


def _visible_gold_set(snapshot: dict[str, Any]) -> set[tuple[int, int]]:
    return {(item["x"], item["y"]) for item in _get_gold_positions(snapshot)}


def _guard_position_set(snapshot: dict[str, Any]) -> set[tuple[int, int]]:
    positions = set()
    for guard in snapshot.get("guards") or []:
        if not isinstance(guard, dict):
            continue
        x = _to_int(guard.get("x"))
        y = _to_int(guard.get("y"))
        if x is not None and y is not None:
            positions.add((x, y))
    return positions


def _can_enter_tile(rows: list[str], x: int, y: int, guard_positions: set[tuple[int, int]]) -> tuple[bool, str]:
    tile = _terrain_at(rows, x, y)
    if tile is None:
        return False, "out-of-bounds"
    if tile in BLOCKING_TILES:
        return False, f"blocked by `{tile}`"
    if (x, y) in guard_positions:
        return False, "occupied by guard"
    return True, "open"


def _history_position(item: dict[str, Any], phase: str) -> dict[str, Any]:
    phase_value = item.get(phase)
    if isinstance(phase_value, dict):
        runner = phase_value.get("runner")
        if isinstance(runner, dict):
            return runner
    return {}


def _history_gold_count(item: dict[str, Any], phase: str) -> int | None:
    phase_value = item.get(phase)
    if not isinstance(phase_value, dict):
        return None
    return _to_int(phase_value.get("goldCount"))


def _history_changed_position(item: dict[str, Any]) -> tuple[bool, bool]:
    before = _history_position(item, "before")
    after = _history_position(item, "after")
    before_x = _to_int(before.get("x"))
    before_y = _to_int(before.get("y"))
    after_x = _to_int(after.get("x"))
    after_y = _to_int(after.get("y"))
    if None in {before_x, before_y, after_x, after_y}:
        return False, False
    return before_x != after_x, before_y != after_y


def _history_collected_gold(item: dict[str, Any]) -> bool:
    before = _history_gold_count(item, "before")
    after = _history_gold_count(item, "after")
    if before is None or after is None:
        return False
    return after < before


def _history_has_position_samples(history: list[dict[str, Any]]) -> bool:
    return any(_history_position(item or {}, "before") or _history_position(item or {}, "after") for item in history)


def find_nearest_gold_candidates(snapshot: dict[str, Any], limit: int = 4) -> list[dict[str, Any]]:
    runner = _get_runner(snapshot)
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    if runner_x is None or runner_y is None:
        return []

    candidates = []
    for position in _get_gold_positions(snapshot):
        distance = abs(position["x"] - runner_x) + abs(position["y"] - runner_y)
        candidates.append(
            {
                "x": position["x"],
                "y": position["y"],
                "distance": distance,
                "sameRow": position["y"] == runner_y,
                "direction": _direction_label(runner_x, position["x"]),
            }
        )

    candidates.sort(
        key=lambda item: (
            0 if item["sameRow"] else 1,
            item["distance"],
            abs(item["x"] - runner_x),
            item["y"],
        )
    )
    return candidates[: max(1, limit)]


def find_row_ladders(snapshot: dict[str, Any], limit: int = 6) -> list[dict[str, Any]]:
    runner = _get_runner(snapshot)
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    if runner_x is None or runner_y is None:
        return []

    rows = _get_terrain_grid(snapshot)
    ladders = []
    if runner_y < 0 or runner_y >= len(rows):
        return []
    row = rows[runner_y]
    ladder_tiles = _active_ladder_tiles(snapshot)
    for x, char in enumerate(row):
        if char not in ladder_tiles:
            continue
        ladders.append(
            {
                "x": x,
                "y": runner_y,
                "distance": abs(x - runner_x),
                "direction": _direction_label(runner_x, x),
                "visible": True,
                "tile": char,
            }
        )

    ladders.sort(key=lambda item: (item["distance"], item["x"]))
    return ladders[: max(1, limit)]


def get_ladder_affordance(snapshot: dict[str, Any]) -> dict[str, Any]:
    runner = _get_runner(snapshot)
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    rows = _get_terrain_grid(snapshot)
    if runner_x is None or runner_y is None:
        return {
            "onLadder": False,
            "adjacentToLadder": False,
            "nearestRowLadder": None,
            "recommendedAction": None,
            "detail": "Runner coordinates are unavailable.",
        }

    row_ladders = find_row_ladders(snapshot, limit=6)
    nearest = row_ladders[0] if row_ladders else None
    current_tile = _terrain_at(rows, runner_x, runner_y)
    gold_complete = _is_gold_complete(snapshot)
    ladder_tiles = _active_ladder_tiles(snapshot)
    on_ladder = current_tile in ladder_tiles
    on_exit_ladder = gold_complete and current_tile == "S"
    adjacent = bool(nearest and nearest["distance"] == 1)
    recommended_action = None
    if on_ladder:
        recommended_action = "up" if runner_y > 0 else "down"
    elif adjacent and nearest:
        recommended_action = nearest["direction"]

    if on_exit_ladder:
        detail = (
            f"Runner is standing on the revealed exit ladder `S` at ({runner_x},{runner_y}); "
            f"use {recommended_action} to climb the exit route."
        )
    elif on_ladder:
        detail = (
            f"Runner is standing on a visible ladder `{current_tile}` at ({runner_x},{runner_y}); "
            f"use {recommended_action} to change row instead of moving horizontally."
        )
    elif adjacent and nearest:
        detail = (
            f"Runner is adjacent to a visible ladder `{nearest['tile']}` at ({nearest['x']},{nearest['y']}); "
            f"move {nearest['direction']} to line up, then climb."
        )
    elif nearest:
        detail = (
            f"Nearest visible ladder `{nearest['tile']}` on runner row is ({nearest['x']},{nearest['y']}), "
            f"{nearest['distance']} tiles to the {nearest['direction']}."
        )
    else:
        detail = "No active ladder is on the runner row."

    return {
        "onLadder": on_ladder,
        "onExitLadder": on_exit_ladder,
        "adjacentToLadder": adjacent,
        "nearestRowLadder": nearest,
        "recommendedAction": recommended_action,
        "detail": detail,
    }


def get_movement_affordance(snapshot: dict[str, Any]) -> dict[str, Any]:
    runner = _get_runner(snapshot)
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    rows = _get_terrain_grid(snapshot)
    guard_positions = _guard_position_set(snapshot)
    if runner_x is None or runner_y is None:
        return {
            "currentTile": None,
            "canMoveLeft": False,
            "canMoveRight": False,
            "canMoveUp": False,
            "canMoveDown": False,
            "verticalAffordance": "runner coordinates unavailable",
            "details": {},
        }

    current_tile = _terrain_at(rows, runner_x, runner_y)
    above_tile = _terrain_at(rows, runner_x, runner_y - 1)
    below_tile = _terrain_at(rows, runner_x, runner_y + 1)
    left_ok, left_reason = _can_enter_tile(rows, runner_x - 1, runner_y, guard_positions)
    right_ok, right_reason = _can_enter_tile(rows, runner_x + 1, runner_y, guard_positions)

    ladder_tiles = _active_ladder_tiles(snapshot)
    can_move_up = current_tile in ladder_tiles
    can_move_down = current_tile in ladder_tiles or below_tile in ladder_tiles
    vertical_affordance = (
        "up/down currently valid on ladder"
        if current_tile in ladder_tiles
        else "down valid because ladder continues below"
        if below_tile in ladder_tiles
        else "no vertical climb is valid from current tile"
    )

    return {
        "currentTile": _display_tile(current_tile),
        "canMoveLeft": left_ok,
        "canMoveRight": right_ok,
        "canMoveUp": can_move_up,
        "canMoveDown": can_move_down,
        "verticalAffordance": vertical_affordance,
        "details": {
            "left": {
                "target": {"x": runner_x - 1, "y": runner_y, "tile": _display_tile(_terrain_at(rows, runner_x - 1, runner_y))},
                "reason": left_reason,
            },
            "right": {
                "target": {"x": runner_x + 1, "y": runner_y, "tile": _display_tile(_terrain_at(rows, runner_x + 1, runner_y))},
                "reason": right_reason,
            },
            "up": {
                "target": {"x": runner_x, "y": runner_y - 1, "tile": _display_tile(above_tile)},
                "reason": "runner is on ladder" if can_move_up else "runner is not on a ladder",
            },
            "down": {
                "target": {"x": runner_x, "y": runner_y + 1, "tile": _display_tile(below_tile)},
                "reason": "runner is on or above ladder" if can_move_down else "no ladder below/current",
            },
        },
    }


def get_dig_affordance(snapshot: dict[str, Any]) -> dict[str, Any]:
    runner = _get_runner(snapshot)
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    rows = _get_terrain_grid(snapshot)
    gold_positions = _visible_gold_set(snapshot)
    guard_positions = _guard_position_set(snapshot)
    risk = assess_guard_risk(snapshot)
    nearest_guard = risk.get("nearestSameRowGuard") or {}

    if runner_x is None or runner_y is None:
        return {
            "canDigLeft": False,
            "canDigRight": False,
            "left": None,
            "right": None,
            "detail": "runner coordinates unavailable",
        }

    def side_info(direction: str, dx: int) -> dict[str, Any]:
        side_x = runner_x + dx
        side_y = runner_y
        target_x = runner_x + dx
        target_y = runner_y + 1
        side_tile = _terrain_at(rows, side_x, side_y)
        target_tile = _terrain_at(rows, target_x, target_y)
        side_clear = side_tile == " " and (side_x, side_y) not in gold_positions and (side_x, side_y) not in guard_positions
        target_diggable = target_tile == "#"
        can_dig = side_clear and target_diggable
        guard_could_fall = (
            can_dig
            and nearest_guard.get("direction") == direction
            and (_to_int(nearest_guard.get("distance")) or 99) <= 4
        )
        reason = "valid defensive dig target" if can_dig else "blocked"
        if not side_clear:
            reason = "side cell is not empty"
        elif not target_diggable:
            reason = "lower target is not `#`"
        return {
            "side": direction,
            "sideCell": {"x": side_x, "y": side_y, "tile": _display_tile(side_tile)},
            "targetCell": {"x": target_x, "y": target_y, "tile": _display_tile(target_tile)},
            "canDig": can_dig,
            "guardCouldFall": guard_could_fall,
            "reason": reason,
        }

    left = side_info("left", -1)
    right = side_info("right", 1)
    return {
        "canDigLeft": left["canDig"],
        "canDigRight": right["canDig"],
        "left": left,
        "right": right,
        "detail": (
            "dig trap available"
            if left["canDig"] or right["canDig"]
            else "no legal dig target from current tile"
        ),
    }


def get_escape_affordance(snapshot: dict[str, Any]) -> dict[str, Any]:
    risk = assess_guard_risk(snapshot)
    movement = get_movement_affordance(snapshot)
    dig = get_dig_affordance(snapshot)
    nearest_guard = risk.get("nearestSameRowGuard") or {}
    guard_direction = nearest_guard.get("direction")
    pressure = risk.get("risk") in {"high", "critical"}
    actions = []

    if pressure:
        if movement["canMoveUp"]:
            actions.append({"action": "up", "type": "climb", "reason": "valid climb away from same-row pressure"})
        elif movement["canMoveDown"]:
            actions.append({"action": "down", "type": "climb", "reason": "valid ladder descent away from same-row pressure"})

        if guard_direction == "left" and dig["canDigLeft"]:
            actions.append({"action": "dig_left", "type": "trap", "reason": "dig left can trap approaching guard"})
        if guard_direction == "right" and dig["canDigRight"]:
            actions.append({"action": "dig_right", "type": "trap", "reason": "dig right can trap approaching guard"})

        if guard_direction == "left" and movement["canMoveRight"]:
            actions.append({"action": "right", "type": "retreat", "reason": "move away from guard on the left"})
        if guard_direction == "right" and movement["canMoveLeft"]:
            actions.append({"action": "left", "type": "retreat", "reason": "move away from guard on the right"})

    return {
        "guardPressure": risk.get("risk"),
        "nearestSameRowGuard": nearest_guard or None,
        "recommendedActions": actions,
        "detail": actions[0]["reason"] if actions else "no urgent escape action identified",
    }


def assess_guard_risk(snapshot: dict[str, Any]) -> dict[str, Any]:
    runner = _get_runner(snapshot)
    guards = snapshot.get("guards") or []
    grid = _get_terrain_grid(snapshot)
    width = _grid_width(grid)

    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    if runner_x is None or runner_y is None:
        return {"risk": "unknown", "nearestGuardDistance": None, "sameRowGuards": []}

    distances = []
    same_row = []
    nearest_same_row = None
    for guard in guards:
        if not isinstance(guard, dict):
            continue
        guard_x = _to_int(guard.get("x"))
        guard_y = _to_int(guard.get("y"))
        if guard_x is None or guard_y is None:
            continue
        distance = abs(guard_x - runner_x) + abs(guard_y - runner_y)
        distances.append(distance)
        if guard_y == runner_y:
            info = {
                "x": guard_x,
                "distance": abs(guard_x - runner_x),
                "direction": _direction_label(runner_x, guard_x),
            }
            same_row.append(info)
            if nearest_same_row is None or info["distance"] < nearest_same_row["distance"]:
                nearest_same_row = info

    nearest = min(distances) if distances else None
    if nearest is None:
        risk = "low"
    elif nearest <= 1:
        risk = "critical"
    elif nearest <= 3:
        risk = "high"
    elif nearest <= 5:
        risk = "medium"
    else:
        risk = "low"
    return {
        "risk": risk,
        "nearestGuardDistance": nearest,
        "sameRowGuards": sorted(same_row, key=lambda item: item["distance"])[:4],
        "nearestSameRowGuard": nearest_same_row,
        "runnerOnEdge": _is_edge(runner_x, width),
    }


def detect_progress_stall(
    snapshot: dict[str, Any], history: list[dict[str, Any]], window: int = 8
) -> dict[str, Any]:
    runner = _get_runner(snapshot)
    runner_x = _to_int(runner.get("x")) or 0
    grid_width = _grid_width(_get_terrain_grid(snapshot))

    recent = history[-max(4, min(24, int(window))):]
    action_names = []
    horizontal_actions = []
    for item in recent:
        key_code = _to_int((item or {}).get("keyCode"))
        if key_code in HORIZONTAL_KEYCODES:
            direction = HORIZONTAL_KEYCODES[key_code]
            action_names.append(direction)
            horizontal_actions.append(direction)
        elif key_code in VERTICAL_KEYCODES:
            action_names.append(VERTICAL_KEYCODES[key_code])
        elif key_code in DIG_KEYCODES:
            action_names.append(DIG_KEYCODES[key_code])
        elif key_code == STOP_KEYCODE:
            action_names.append("stop")
        elif key_code is not None:
            action_names.append(str(key_code))

    counts = Counter(horizontal_actions)
    dominant_direction = None
    dominant_count = 0
    if counts:
        dominant_direction, dominant_count = counts.most_common(1)[0]

    vertical_recent = any(name in {"up", "down"} for name in action_names)
    dig_recent = any(name.startswith("dig_") for name in action_names)
    stop_recent = any(name == "stop" for name in action_names)
    has_position_samples = _history_has_position_samples(recent)
    x_change_recent = False
    row_change_recent = False
    gold_collected_recent = False
    if has_position_samples:
        for item in recent:
            x_changed, y_changed = _history_changed_position(item or {})
            x_change_recent = x_change_recent or x_changed
            row_change_recent = row_change_recent or y_changed
            gold_collected_recent = gold_collected_recent or _history_collected_gold(item or {})
    same_state_streak = bool(recent) and all(
        (item or {}).get("state") == snapshot.get("gameStateName") for item in recent
    )
    repeated_same_direction = dominant_count >= max(4, len(recent) - 2)
    oscillating = len(horizontal_actions) >= 4 and len(set(horizontal_actions[-6:])) == 2 and all(
        horizontal_actions[index] != horizontal_actions[index - 1]
        for index in range(1, len(horizontal_actions[-6:]))
    )

    edge_direction = None
    if runner_x <= 1:
        edge_direction = "left"
    elif grid_width and runner_x >= max(0, grid_width - 2):
        edge_direction = "right"
    edge_pressure = bool(edge_direction and dominant_direction == edge_direction)

    row_progress_recent = row_change_recent or vertical_recent
    no_progress_signals = not row_progress_recent and not dig_recent and not gold_collected_recent
    horizontal_position_progress = x_change_recent and not oscillating and not edge_pressure
    repeated_stuck_direction = repeated_same_direction and (
        not has_position_samples or not horizontal_position_progress
    )
    stalled = bool(recent) and no_progress_signals and (
        repeated_stuck_direction or oscillating or edge_pressure or (stop_recent and same_state_streak)
    )

    return {
        "stalled": stalled,
        "recentActionCount": len(recent),
        "dominantDirection": dominant_direction,
        "dominantCount": dominant_count,
        "oscillating": oscillating,
        "edgePressure": edge_pressure,
        "edgeDirection": edge_direction,
        "rowChangeLikelyRecent": row_progress_recent,
        "xChangeRecent": x_change_recent,
        "goldCollectedRecent": gold_collected_recent,
        "hasPositionSamples": has_position_samples,
        "digRecent": dig_recent,
        "sameStateStreak": same_state_streak,
        "recentActions": action_names[-8:],
    }


def assess_safe_progress_options(
    snapshot: dict[str, Any], history: list[dict[str, Any]], limit: int = 4
) -> dict[str, Any]:
    risk = assess_guard_risk(snapshot)
    nearest_gold = find_nearest_gold_candidates(snapshot, limit=4)
    row_ladders = find_row_ladders(snapshot, limit=4)
    ladder_affordance = get_ladder_affordance(snapshot)
    escape_affordance = get_escape_affordance(snapshot)
    stall = detect_progress_stall(snapshot, history)
    gold_complete = _is_gold_complete(snapshot)

    options = []
    same_row_gold = [item for item in nearest_gold if item["sameRow"]]
    visible_ladders = [item for item in row_ladders if item["visible"] and item["tile"] == "H"]
    exit_ladders = [item for item in row_ladders if item["visible"] and item["tile"] == "S"]

    if risk["risk"] in {"critical", "high"} and escape_affordance["recommendedActions"]:
        for action in escape_affordance["recommendedActions"][:2]:
            options.append(
                {
                    "type": f"escape_{action['type']}",
                    "detail": action["reason"],
                }
            )

    if risk["risk"] not in {"critical", "high"}:
        if ladder_affordance["onLadder"]:
            options.append(
                {
                    "type": "climb_current_ladder",
                    "detail": ladder_affordance["detail"],
                }
            )
        if gold_complete:
            for ladder in exit_ladders[:2]:
                options.append(
                    {
                        "type": "climb_exit_ladder",
                        "detail": (
                            f"Revealed exit ladder `S` at ({ladder['x']},{ladder['y']}) is on the runner row, "
                            f"{ladder['distance']} tiles away to the {ladder['direction']}."
                        ),
                    }
                )
        else:
            for gold in same_row_gold[:2]:
                options.append(
                    {
                        "type": "collect_gold",
                        "detail": (
                            f"Gold at ({gold['x']},{gold['y']}) is nearby on the same row, "
                            f"{gold['distance']} tiles away to the {gold['direction']}."
                        ),
                    }
                )
            for ladder in visible_ladders[:2]:
                options.append(
                    {
                        "type": "climb_ladder",
                        "detail": (
                            f"Ladder at ({ladder['x']},{ladder['y']}) is on the runner row, "
                            f"{ladder['distance']} tiles away to the {ladder['direction']}."
                        ),
                    }
                )

    if not options and nearest_gold:
        gold = nearest_gold[0]
        options.append(
            {
                "type": "advance_to_gold",
                "detail": (
                    f"Nearest gold is at ({gold['x']},{gold['y']}) with distance {gold['distance']}."
                ),
            }
        )

    if stall["stalled"] and stall["dominantDirection"]:
        options.append(
            {
                "type": "break_stall",
                "detail": (
                    "Looping or stall is detected. Avoid another "
                    f"{stall['dominantDirection']} retreat unless danger is immediate."
                ),
            }
        )

    return {
        "risk": risk["risk"],
        "immediateBlocker": risk["risk"] == "critical",
        "sameRowGoldCount": len(same_row_gold),
        "rowLadderCount": len(visible_ladders),
        "exitLadderCount": len(exit_ladders),
        "ladderAffordance": ladder_affordance,
        "movementAffordance": get_movement_affordance(snapshot),
        "digAffordance": get_dig_affordance(snapshot),
        "escapeAffordance": escape_affordance,
        "stallDetected": stall["stalled"],
        "options": options[: max(1, limit)],
    }


def build_reasoning_tools(snapshot: dict[str, Any], history: list[dict[str, Any]]) -> list:
    runner = _get_runner(snapshot)
    guards = snapshot.get("guards") or []
    grid = _get_terrain_grid(snapshot)

    def summarize_snapshot() -> dict[str, Any]:
        """Summarize the current board state, runner position, guard pressure, and remaining goal state."""

        guard_positions = [{"x": guard.get("x"), "y": guard.get("y")} for guard in guards[:6]]
        gold_tiles = len(_get_gold_positions(snapshot))
        return {
            "runner": {
                "x": runner.get("x"),
                "y": runner.get("y"),
                "action": runner.get("actionName"),
            },
            "guards": {"count": len(guards), "positions": guard_positions},
            "goldTilesVisible": gold_tiles,
            "goldCountRemaining": snapshot.get("goldCount"),
            "goldComplete": snapshot.get("goldComplete"),
            "gameState": snapshot.get("gameStateName"),
            "tick": snapshot.get("tick"),
            "ladderAffordance": get_ladder_affordance(snapshot),
            "movementAffordance": get_movement_affordance(snapshot),
            "digAffordance": get_dig_affordance(snapshot),
            "escapeAffordance": get_escape_affordance(snapshot),
        }

    def detect_looping(window: int = 8) -> dict[str, Any]:
        """Detect whether recent actions look repetitive or stuck in a short oscillation loop."""

        recent = history[-max(2, min(24, int(window))):]
        actions = [f"{item.get('keyCode')}:{item.get('ticks')}" for item in recent]
        action_counts = Counter(actions)
        most_common = action_counts.most_common(2)
        looping = len(most_common) > 0 and most_common[0][1] >= max(3, len(recent) // 2)
        return {
            "looping": looping,
            "recentActionCount": len(recent),
            "mostCommonActions": most_common,
            "lastState": recent[-1].get("state") if recent else None,
        }

    def find_nearest_gold_candidates_tool(limit: int = 4) -> dict[str, Any]:
        """List the nearest gold targets, prioritizing same-row gold for immediate progress."""

        return {"candidates": find_nearest_gold_candidates(snapshot, limit=max(1, int(limit)))}

    def find_row_ladders_tool(limit: int = 6) -> dict[str, Any]:
        """List active ladder opportunities on the runner row for safe upward progress or exit climbing."""

        return {"ladders": find_row_ladders(snapshot, limit=max(1, int(limit)))}

    def inspect_ladder_affordance() -> dict[str, Any]:
        """Explain whether the runner is on or next to a ladder and what vertical action changes route."""

        return get_ladder_affordance(snapshot)

    def inspect_movement_affordance() -> dict[str, Any]:
        """List which movement directions are physically valid from the current tile."""

        return get_movement_affordance(snapshot)

    def inspect_dig_affordance() -> dict[str, Any]:
        """List legal defensive dig targets using the legacy ok2Dig side/target-cell rules."""

        return get_dig_affordance(snapshot)

    def inspect_escape_affordance() -> dict[str, Any]:
        """Recommend valid escape actions under same-row guard pressure."""

        return get_escape_affordance(snapshot)

    def detect_progress_stall_tool(window: int = 8) -> dict[str, Any]:
        """Detect repeated retreat or oscillation patterns that are not producing puzzle progress."""

        return detect_progress_stall(snapshot, history, window=window)

    def assess_guard_risk_tool() -> dict[str, Any]:
        """Assess whether nearby guards create immediate danger and which direction seems safer."""

        return assess_guard_risk(snapshot)

    def assess_safe_progress_options_tool(limit: int = 4) -> dict[str, Any]:
        """Summarize nearby gold, ladders, and stall-breaking progress options."""

        return assess_safe_progress_options(snapshot, history, limit=max(1, int(limit)))

    def suggest_subgoal() -> dict[str, Any]:
        """Suggest a short-term puzzle objective for the next action burst."""

        progress = assess_safe_progress_options(snapshot, history, limit=3)
        nearest_gold = find_nearest_gold_candidates(snapshot, limit=1)
        row_ladders = [item for item in find_row_ladders(snapshot, limit=2) if item["visible"]]
        ladder_affordance = get_ladder_affordance(snapshot)
        escape_affordance = get_escape_affordance(snapshot)

        if _is_gold_complete(snapshot):
            exit_ladder = next((item for item in row_ladders if item["tile"] == "S"), None)
            objective = "reach_exit_ladder"
            detail = (
                f"All gold is collected. Move onto revealed exit ladder `S` at ({exit_ladder['x']},{exit_ladder['y']}) and climb."
                if exit_ladder
                else "All gold is collected. Move onto the revealed exit ladder `S` and climb upward."
            )
        elif progress["risk"] in {"critical", "high"} and escape_affordance["recommendedActions"]:
            objective = "escape_guard_pressure"
            detail = escape_affordance["recommendedActions"][0]["reason"]
        elif progress["risk"] not in {"critical", "high"} and ladder_affordance["onLadder"]:
            objective = "climb_current_ladder"
            detail = ladder_affordance["detail"]
        elif progress["risk"] not in {"critical", "high"} and nearest_gold and nearest_gold[0]["sameRow"]:
            gold = nearest_gold[0]
            objective = "collect_nearby_gold"
            detail = (
                f"Prefer the same-row gold at ({gold['x']},{gold['y']}) before retreating further."
            )
        elif progress["risk"] not in {"critical", "high"} and row_ladders:
            ladder = row_ladders[0]
            objective = "climb_for_progress"
            detail = f"Use the ladder at ({ladder['x']},{ladder['y']}) to change route and gain height."
        elif progress["stallDetected"]:
            objective = "break_retreat_loop"
            detail = "Stop repeating the same retreat direction. Switch to gold or ladder progress."
        elif guards:
            objective = "create_space"
            detail = "Use ladders, ropes, or a short retreat to widen distance from guards."
        else:
            objective = "collect_accessible_gold"
            detail = "Advance toward the nearest reachable gold without self-trapping."
        return {"objective": objective, "detail": detail}

    def evaluate_last_action() -> dict[str, Any]:
        """Evaluate whether the most recent action improved progress or likely caused a stall."""

        if not history:
            return {"status": "unknown", "detail": "No prior action history is available."}

        last = history[-1]
        detail = "The last action changed state or position."
        status = "progress"
        if last.get("state") == snapshot.get("gameStateName"):
            detail = "The last action did not change the reported game state."
            status = "neutral"
        if snapshot.get("gameStateName") == "runner_dead":
            detail = "The previous move burst led to death."
            status = "failure"
        if detect_progress_stall(snapshot, history)["stalled"]:
            detail = "Recent actions look stalled. Repeating the same retreat is risky."
            status = "stall"
        return {
            "status": status,
            "detail": detail,
            "lastAction": {
                "keyCode": last.get("keyCode"),
                "ticks": last.get("ticks"),
                "reason": last.get("reason"),
            },
        }

    return [
        summarize_snapshot,
        detect_looping,
        find_nearest_gold_candidates_tool,
        find_row_ladders_tool,
        inspect_ladder_affordance,
        inspect_movement_affordance,
        inspect_dig_affordance,
        inspect_escape_affordance,
        detect_progress_stall_tool,
        assess_guard_risk_tool,
        assess_safe_progress_options_tool,
        suggest_subgoal,
        evaluate_last_action,
    ]
