from __future__ import annotations

from typing import Any


LEFT_KEYCODE = 37
UP_KEYCODE = 38
RIGHT_KEYCODE = 39
DOWN_KEYCODE = 40
STOP_KEYCODE = 32
DIG_LEFT_KEYCODE = 90
DIG_RIGHT_KEYCODE = 88

BLOCKING_TILES = {"#", "@"}


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _get_runner(snapshot: dict[str, Any]) -> dict[str, Any]:
    runner = snapshot.get("runner") or {}
    return runner if isinstance(runner, dict) else {}


def _get_terrain_grid(snapshot: dict[str, Any]) -> list[str]:
    rows = snapshot.get("terrainGrid") or []
    if not isinstance(rows, list):
        return []
    return [row if isinstance(row, str) else str(row) for row in rows]


def _get_active_grid(snapshot: dict[str, Any]) -> list[str]:
    rows = snapshot.get("grid") or []
    if not isinstance(rows, list):
        return []
    return [row if isinstance(row, str) else str(row) for row in rows]


def _is_gold_complete(snapshot: dict[str, Any]) -> bool:
    gold = snapshot.get("gold") or {}
    if isinstance(gold, dict) and "complete" in gold:
        return bool(gold.get("complete"))
    return bool(snapshot.get("goldComplete"))


def _is_god_mode(snapshot: dict[str, Any]) -> bool:
    return bool(snapshot.get("godMode"))


def _active_ladder_tiles(snapshot: dict[str, Any]) -> set[str]:
    return {"H", "S"} if _is_gold_complete(snapshot) else {"H"}


def _get_gold_positions(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    gold = snapshot.get("gold") or {}
    visible_positions = gold.get("visiblePositions")
    positions = []
    if isinstance(visible_positions, list):
        for item in visible_positions:
            if not isinstance(item, dict):
                continue
            x = _to_int(item.get("x"))
            y = _to_int(item.get("y"))
            if x is not None and y is not None:
                positions.append({"x": x, "y": y, "tile": "$", "source": "visible"})

    carried_positions = gold.get("carriedByGuards")
    if isinstance(carried_positions, list):
        for item in carried_positions:
            if not isinstance(item, dict):
                continue
            x = _to_int(item.get("x"))
            y = _to_int(item.get("y"))
            if x is not None and y is not None:
                positions.append(
                    {
                        "x": x,
                        "y": y,
                        "tile": "$",
                        "source": "guard",
                        "guardId": item.get("id"),
                    }
                )
    return positions


def _nearest_off_row_gold(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    runner = _get_runner(snapshot)
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    if runner_x is None or runner_y is None:
        return None

    candidates = []
    for position in _get_gold_positions(snapshot):
        if position["y"] == runner_y:
            continue
        distance = abs(position["x"] - runner_x) + abs(position["y"] - runner_y)
        candidates.append(
            {
                "x": position["x"],
                "y": position["y"],
                "distance": distance,
                "direction": _direction_label(runner_x, position["x"]),
                "verticalDirection": "below" if position["y"] > runner_y else "above",
            }
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item["distance"], abs(item["x"] - runner_x), item["y"]))
    return candidates[0]


def _grid_width(rows: list[str]) -> int:
    return max((len(row) for row in rows), default=0)


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


def _can_enter_tile(
    rows: list[str],
    x: int,
    y: int,
    guard_positions: set[tuple[int, int]],
    *,
    god_mode: bool = False,
) -> tuple[bool, str]:
    tile = _terrain_at(rows, x, y)
    if tile is None:
        return False, "out-of-bounds"
    if tile in BLOCKING_TILES:
        return False, f"blocked by `{tile}`"
    if (x, y) in guard_positions:
        if god_mode:
            return True, "occupied by guard, passable in god mode"
        return False, "occupied by guard"
    return True, "open"


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
                "source": position.get("source", "visible"),
                "guardId": position.get("guardId"),
            }
        )

    candidates.sort(
        key=lambda item: (
            0 if item["sameRow"] else 1,
            0 if item.get("source") == "visible" else 1,
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
    if runner_y < 0 or runner_y >= len(rows):
        return []

    ladders = []
    ladder_tiles = _active_ladder_tiles(snapshot)
    for x, char in enumerate(rows[runner_y]):
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
            "onExitLadder": False,
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
    god_mode = _is_god_mode(snapshot)
    if runner_x is None or runner_y is None:
        return {
            "currentTile": None,
            "godMode": god_mode,
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
    left_ok, left_reason = _can_enter_tile(
        rows, runner_x - 1, runner_y, guard_positions, god_mode=god_mode
    )
    right_ok, right_reason = _can_enter_tile(
        rows, runner_x + 1, runner_y, guard_positions, god_mode=god_mode
    )

    ladder_tiles = _active_ladder_tiles(snapshot)
    can_move_up = current_tile in ladder_tiles
    can_drop_from_rope = current_tile == "-" and below_tile not in {"#", "@", "H", "S", "0", None}
    can_descend_from_ladder = current_tile in ladder_tiles and below_tile not in {"#", "@", None}
    can_move_down = can_descend_from_ladder or below_tile in ladder_tiles or can_drop_from_rope
    vertical_affordance = (
        "up/down currently valid on ladder"
        if current_tile in ladder_tiles and can_descend_from_ladder
        else "down drops from rope"
        if can_drop_from_rope
        else "down valid because ladder continues below"
        if below_tile in ladder_tiles
        else "no vertical climb is valid from current tile"
    )

    return {
        "currentTile": _display_tile(current_tile),
        "godMode": god_mode,
        "canMoveLeft": left_ok,
        "canMoveRight": right_ok,
        "canMoveUp": can_move_up,
        "canMoveDown": can_move_down,
        "verticalAffordance": vertical_affordance,
        "details": {
            "left": {
                "target": {
                    "x": runner_x - 1,
                    "y": runner_y,
                    "tile": _display_tile(_terrain_at(rows, runner_x - 1, runner_y)),
                },
                "reason": left_reason,
            },
            "right": {
                "target": {
                    "x": runner_x + 1,
                    "y": runner_y,
                    "tile": _display_tile(_terrain_at(rows, runner_x + 1, runner_y)),
                },
                "reason": right_reason,
            },
            "up": {
                "target": {"x": runner_x, "y": runner_y - 1, "tile": _display_tile(above_tile)},
                "reason": "runner is on ladder" if can_move_up else "runner is not on a ladder",
            },
            "down": {
                "target": {"x": runner_x, "y": runner_y + 1, "tile": _display_tile(below_tile)},
                "reason": (
                    "runner is on or above ladder"
                    if can_descend_from_ladder or below_tile in ladder_tiles
                    else "runner can drop from rope"
                    if can_drop_from_rope
                    else "no ladder below/current"
                ),
            },
        },
    }


def get_dig_affordance(snapshot: dict[str, Any]) -> dict[str, Any]:
    runner = _get_runner(snapshot)
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    rows = _get_terrain_grid(snapshot)
    active_rows = _get_active_grid(snapshot) or rows
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
        side_tile = _terrain_at(active_rows, side_x, side_y)
        target_tile = _terrain_at(active_rows, target_x, target_y)
        side_clear = (
            side_tile == " "
            and (side_x, side_y) not in gold_positions
            and (side_x, side_y) not in guard_positions
        )
        target_diggable = target_tile == "#"
        can_dig = side_clear and target_diggable
        guard_could_fall = (
            can_dig
            and nearest_guard.get("direction") == direction
            and (_to_int(nearest_guard.get("distance")) or 99) <= 4
        )
        reason = "valid dig target" if can_dig else "blocked"
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
            "dig target available"
            if left["canDig"] or right["canDig"]
            else "no legal dig target from current tile"
        ),
    }


def get_route_access_affordance(snapshot: dict[str, Any]) -> dict[str, Any]:
    runner = _get_runner(snapshot)
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    dig = get_dig_affordance(snapshot)
    same_row_gold = [item for item in find_nearest_gold_candidates(snapshot, limit=4) if item["sameRow"]]
    row_ladders = [
        item for item in find_row_ladders(snapshot, limit=4) if item["visible"] and item["tile"] == "H"
    ]
    off_row_gold = _nearest_off_row_gold(snapshot)

    if runner_x is None or runner_y is None:
        return {
            "available": False,
            "recommendedAction": None,
            "offRowGoldTarget": off_row_gold,
            "reason": "runner coordinates unavailable",
        }
    if _is_gold_complete(snapshot):
        return {
            "available": False,
            "recommendedAction": None,
            "offRowGoldTarget": off_row_gold,
            "reason": "all gold is collected; use exit routing",
        }
    if same_row_gold:
        return {
            "available": False,
            "recommendedAction": None,
            "offRowGoldTarget": off_row_gold,
            "reason": "same-row gold is available; collect it before access digging",
        }
    if row_ladders and not ladder_route_is_blocked_for_lower_gold(snapshot, off_row_gold):
        return {
            "available": False,
            "recommendedAction": None,
            "offRowGoldTarget": off_row_gold,
            "reason": "same-row ladder is available; use ladder route before access digging",
        }
    if not off_row_gold or off_row_gold["verticalDirection"] != "below":
        return {
            "available": False,
            "recommendedAction": None,
            "followAvailable": False,
            "followAction": None,
            "offRowGoldTarget": off_row_gold,
            "reason": "no lower off-row gold target needs access digging",
        }

    preferred_side = off_row_gold.get("direction")
    if preferred_side in {"left", "right"}:
        preferred = dig.get(preferred_side)
        if isinstance(preferred, dict) and not preferred.get("canDig"):
            target_cell = preferred.get("targetCell") or {}
            side_cell = preferred.get("sideCell") or {}
            if target_cell.get("tile") == "." and side_cell.get("tile") == ".":
                return {
                    "available": False,
                    "recommendedAction": None,
                    "followAvailable": True,
                    "followAction": preferred_side,
                    "offRowGoldTarget": off_row_gold,
                    "openedAccessCell": target_cell,
                    "reason": (
                        f"route-access hole at ({target_cell.get('x')},{target_cell.get('y')}) "
                        f"is already open; move {preferred_side} to enter the access route"
                    ),
                }

    options = []
    for action, side in (("dig_left", "left"), ("dig_right", "right")):
        item = dig.get(side)
        if not isinstance(item, dict) or not item.get("canDig"):
            continue
        target_cell = item.get("targetCell") or {}
        target_x = _to_int(target_cell.get("x"))
        if target_x is None:
            continue
        options.append(
            {
                "action": action,
                "side": side,
                "targetCell": target_cell,
                "distanceToGoldX": abs(target_x - off_row_gold["x"]),
                "reason": (
                    f"{action} opens a lower access hole at ({target_cell.get('x')},{target_cell.get('y')}) "
                    f"toward off-row gold at ({off_row_gold['x']},{off_row_gold['y']})"
                ),
            }
        )

    if not options:
        return {
            "available": False,
            "recommendedAction": None,
            "followAvailable": False,
            "followAction": None,
            "offRowGoldTarget": off_row_gold,
            "reason": "off-row gold is below, but no legal access dig is available",
        }

    options.sort(key=lambda item: (item["distanceToGoldX"], 0 if item["side"] == off_row_gold["direction"] else 1))
    return {
        "available": True,
        "recommendedAction": options[0]["action"],
        "followAvailable": False,
        "followAction": None,
        "offRowGoldTarget": off_row_gold,
        "options": options,
        "reason": options[0]["reason"],
    }


def ladder_route_is_blocked_for_lower_gold(
    snapshot: dict[str, Any], off_row_gold: dict[str, Any] | None
) -> bool:
    if not off_row_gold or off_row_gold.get("verticalDirection") != "below":
        return False
    runner = _get_runner(snapshot)
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    target_x = _to_int(off_row_gold.get("x"))
    if runner_x is None or runner_y is None or target_x is None or runner_x != target_x:
        return False
    rows = _get_terrain_grid(snapshot)
    current_tile = _terrain_at(rows, runner_x, runner_y)
    below_tile = _terrain_at(rows, runner_x, runner_y + 1)
    return current_tile in _active_ladder_tiles(snapshot) and below_tile in {"#", "@"}


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
