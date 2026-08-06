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


def _vertical_label(origin_y: int, target_y: int) -> str:
    if target_y < origin_y:
        return "above"
    if target_y > origin_y:
        return "below"
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
    active_rows = _get_active_grid(snapshot) or rows
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
    runner_y_offset = _to_int(runner.get("yOffset")) or 0
    above_tile = _terrain_at(rows, runner_x, runner_y - 1)
    below_tile = _terrain_at(rows, runner_x, runner_y + 1)
    left_ok, left_reason = _can_enter_tile(
        rows, runner_x - 1, runner_y, guard_positions, god_mode=god_mode
    )
    right_ok, right_reason = _can_enter_tile(
        rows, runner_x + 1, runner_y, guard_positions, god_mode=god_mode
    )
    up_ok, up_reason = _can_enter_tile(
        rows, runner_x, runner_y - 1, guard_positions, god_mode=god_mode
    )
    down_ok, down_reason = _can_enter_tile(
        rows, runner_x, runner_y + 1, guard_positions, god_mode=god_mode
    )

    ladder_tiles = _active_ladder_tiles(snapshot)
    can_move_up = current_tile in ladder_tiles and up_ok
    can_drop_from_rope = current_tile == "-" and below_tile not in {"#", "@", "H", "S", "0", None}
    can_descend_from_ladder = current_tile in ladder_tiles and below_tile not in {"#", "@", None}
    can_move_down = down_ok and (
        can_descend_from_ladder or below_tile in ladder_tiles or can_drop_from_rope
    )
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
        "terrainHeight": len(rows),
        "godMode": god_mode,
        "canMoveLeft": left_ok,
        "canMoveRight": right_ok,
        "canMoveUp": can_move_up,
        "canMoveDown": can_move_down,
        "canFinishExitClimb": bool(
            _is_gold_complete(snapshot)
            and runner_x == 18
            and runner_y == 0
            and runner_y_offset > 0
            and current_tile in ladder_tiles
        ),
        "verticalAffordance": vertical_affordance,
        "details": {
            "left": {
                "target": {
                    "x": runner_x - 1,
                    "y": runner_y,
                    "tile": _display_tile(_terrain_at(rows, runner_x - 1, runner_y)),
                },
                "reason": left_reason,
                "wouldFallIntoOpenHole": _is_open_dug_hole(
                    rows, active_rows, runner_x - 1, runner_y + 1
                ),
                "openDugHoleDistance": _nearest_open_dug_hole_distance(
                    rows, active_rows, runner_x, runner_y, direction=-1
                ),
                "openHole": _nearest_open_hole_state(
                    snapshot, runner_x, runner_y, direction=-1
                ),
            },
            "right": {
                "target": {
                    "x": runner_x + 1,
                    "y": runner_y,
                    "tile": _display_tile(_terrain_at(rows, runner_x + 1, runner_y)),
                },
                "reason": right_reason,
                "wouldFallIntoOpenHole": _is_open_dug_hole(
                    rows, active_rows, runner_x + 1, runner_y + 1
                ),
                "openDugHoleDistance": _nearest_open_dug_hole_distance(
                    rows, active_rows, runner_x, runner_y, direction=1
                ),
                "openHole": _nearest_open_hole_state(
                    snapshot, runner_x, runner_y, direction=1
                ),
            },
            "up": {
                "target": {"x": runner_x, "y": runner_y - 1, "tile": _display_tile(above_tile)},
                "reason": (
                    "runner is on ladder and target is open"
                    if can_move_up
                    else up_reason
                    if current_tile in ladder_tiles
                    else "runner is not on a ladder"
                ),
            },
            "down": {
                "target": {"x": runner_x, "y": runner_y + 1, "tile": _display_tile(below_tile)},
                "reason": (
                    down_reason
                    if not down_ok
                    else "runner is on or above ladder"
                    if can_descend_from_ladder or below_tile in ladder_tiles
                    else "runner can drop from rope"
                    if can_drop_from_rope
                    else "no ladder below/current"
                ),
            },
        },
    }


def _is_open_dug_hole(
    terrain_rows: list[str], active_rows: list[str], x: int, y: int
) -> bool:
    return _terrain_at(terrain_rows, x, y) == "#" and _terrain_at(active_rows, x, y) == " "


def _nearest_open_dug_hole_distance(
    terrain_rows: list[str],
    active_rows: list[str],
    runner_x: int,
    runner_y: int,
    *,
    direction: int,
    limit: int = 4,
) -> int | None:
    for distance in range(1, limit + 1):
        if _is_open_dug_hole(
            terrain_rows, active_rows, runner_x + direction * distance, runner_y + 1
        ):
            return distance
    return None


def _nearest_open_hole_state(
    snapshot: dict[str, Any], runner_x: int, runner_y: int, *, direction: int
) -> dict[str, Any] | None:
    holes = []
    trapped_guard_cells = {
        (_to_int(guard.get("x")), _to_int(guard.get("y")))
        for guard in snapshot.get("guards") or []
        if isinstance(guard, dict) and guard.get("actionName") == "in_hole"
    }
    for hole in snapshot.get("openHoles") or []:
        if not isinstance(hole, dict):
            continue
        x = _to_int(hole.get("x"))
        y = _to_int(hole.get("y"))
        if x is None or y != runner_y + 1:
            continue
        distance = (x - runner_x) * direction
        if 1 <= distance <= 4:
            holes.append(
                {
                    "x": x,
                    "y": y,
                    "distance": distance,
                    "frameIndex": _to_int(hole.get("frameIndex")) or 0,
                    "frameTime": _to_int(hole.get("frameTime")) or 0,
                    "occupiedByTrappedGuard": (x, y) in trapped_guard_cells,
                }
            )
    holes.sort(key=lambda item: item["distance"])
    return holes[0] if holes else None


def get_dig_affordance(snapshot: dict[str, Any]) -> dict[str, Any]:
    runner = _get_runner(snapshot)
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    runner_centered = (
        (_to_int(runner.get("xOffset")) or 0) == 0
        and (_to_int(runner.get("yOffset")) or 0) == 0
    )
    rows = _get_terrain_grid(snapshot)
    active_rows = _get_active_grid(snapshot) or rows
    gold_positions = _visible_gold_set(snapshot)
    guard_positions = _guard_position_set(snapshot)
    risk = assess_guard_risk(snapshot)
    nearest_guard = risk.get("nearestSameRowGuard") or {}
    pressure_guard = risk.get("pressureGuard") or {}
    if (
        not nearest_guard
        and pressure_guard.get("relativeY") == "above"
        and pressure_guard.get("motion") in {"down", "fall"}
        and (_to_int(pressure_guard.get("distance")) or 99) <= 3
    ):
        nearest_guard = pressure_guard

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
        bottom_boundary = target_y >= len(rows) - 1
        engine_diggable = runner_centered and side_clear and target_diggable
        can_dig = engine_diggable and not bottom_boundary
        guard_could_fall = (
            engine_diggable
            and (nearest_guard.get("side") or nearest_guard.get("relativeX")) == direction
            and (_to_int(nearest_guard.get("distance")) or 99)
            <= (
                5
                if risk.get("runnerOnEdge")
                and nearest_guard.get("closing")
                else 4
            )
        )
        reason = "valid dig target" if can_dig else "blocked"
        if not side_clear:
            reason = "side cell is not empty"
        elif not runner_centered:
            reason = "runner must be centered before digging"
        elif bottom_boundary:
            reason = "bottom terrain row would create an inescapable drop"
        elif not target_diggable:
            reason = "lower target is not `#`"
        return {
            "side": direction,
            "sideCell": {"x": side_x, "y": side_y, "tile": _display_tile(side_tile)},
            "targetCell": {"x": target_x, "y": target_y, "tile": _display_tile(target_tile)},
            "canDig": can_dig,
            "canDefensiveDig": engine_diggable,
            "bottomBoundary": bottom_boundary,
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
    opened_options = []
    for side in ("left", "right"):
        item = dig.get(side)
        if not isinstance(item, dict) or item.get("canDig"):
            continue
        target_cell = item.get("targetCell") or {}
        side_cell = item.get("sideCell") or {}
        if target_cell.get("tile") != "." or side_cell.get("tile") != ".":
            continue
        drop_threat = assess_access_drop_threat(snapshot, target_cell)
        opened_options.append(
            {
                "side": side,
                "targetCell": target_cell,
                "dropThreat": drop_threat,
                "unsafe": bool(drop_threat.get("unsafe")) and not _is_god_mode(snapshot),
                "preferred": side == preferred_side,
            }
        )
    if opened_options:
        opened_options.sort(key=lambda item: (item["unsafe"], not item["preferred"]))
        opened = opened_options[0]
        target_cell = opened["targetCell"]
        if opened["unsafe"]:
            threat = opened["dropThreat"].get("nearestThreat") or {}
            return {
                "available": False,
                "recommendedAction": None,
                "followAvailable": False,
                "followAction": opened["side"],
                "followBlockedByGuard": True,
                "dropThreat": opened["dropThreat"],
                "offRowGoldTarget": off_row_gold,
                "openedAccessCell": target_cell,
                "reason": (
                    f"opened access route at ({target_cell.get('x')},{target_cell.get('y')}) "
                    f"is unsafe while guard {threat.get('id')} is converging below; "
                    "wait for guard clearance before entering"
                ),
            }
        return {
            "available": False,
            "recommendedAction": None,
            "followAvailable": True,
            "followAction": opened["side"],
            "offRowGoldTarget": off_row_gold,
            "openedAccessCell": target_cell,
            "reason": (
                f"route-access hole at ({target_cell.get('x')},{target_cell.get('y')}) "
                f"is already open and guard-clear; move {opened['side']} to enter"
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
                "dropThreat": assess_access_drop_threat(
                    snapshot, target_cell, vertical_limit=8, intercept_limit=10
                ),
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

    options.sort(
        key=lambda item: (
            bool(item["dropThreat"].get("unsafe")) and not _is_god_mode(snapshot),
            item["distanceToGoldX"],
            0 if item["side"] == off_row_gold["direction"] else 1,
        )
    )
    if options[0]["dropThreat"].get("unsafe") and not _is_god_mode(snapshot):
        threat = options[0]["dropThreat"].get("nearestThreat") or {}
        target_cell = options[0]["targetCell"]
        return {
            "available": False,
            "recommendedAction": None,
            "digBlockedByGuard": True,
            "dropThreat": options[0]["dropThreat"],
            "plannedAccessCell": target_cell,
            "offRowGoldTarget": off_row_gold,
            "options": options,
            "reason": (
                f"both access digs are unsafe; guard {threat.get('id')} can intercept "
                f"the best hole at ({target_cell.get('x')},{target_cell.get('y')})"
            ),
        }
    return {
        "available": True,
        "recommendedAction": options[0]["action"],
        "followAvailable": False,
        "followAction": None,
        "offRowGoldTarget": off_row_gold,
        "options": options,
        "reason": options[0]["reason"],
    }


def assess_access_drop_threat(
    snapshot: dict[str, Any],
    target_cell: dict[str, Any],
    *,
    horizontal_limit: int = 2,
    vertical_limit: int = 6,
    intercept_limit: int = 8,
) -> dict[str, Any]:
    """Identify guards close enough to intercept a runner committed to an access drop."""
    target_x = _to_int(target_cell.get("x"))
    target_y = _to_int(target_cell.get("y"))
    if target_x is None or target_y is None:
        return {"unsafe": False, "nearestThreat": None, "threats": []}

    threats = []
    for guard in snapshot.get("guards") or []:
        if not isinstance(guard, dict):
            continue
        guard_x = _to_int(guard.get("x"))
        guard_y = _to_int(guard.get("y"))
        if guard_x is None or guard_y is None or guard_y <= target_y:
            continue
        horizontal_distance = abs(guard_x - target_x)
        vertical_distance = guard_y - target_y
        intercept_distance = horizontal_distance + vertical_distance
        if (
            horizontal_distance > horizontal_limit
            or vertical_distance > vertical_limit
            or intercept_distance > intercept_limit
        ):
            continue
        threats.append(
            {
                "id": guard.get("id"),
                "x": guard_x,
                "y": guard_y,
                "xOffset": _to_int(guard.get("xOffset")) or 0,
                "yOffset": _to_int(guard.get("yOffset")) or 0,
                "motion": str(guard.get("actionName") or "unknown"),
                "horizontalDistance": horizontal_distance,
                "verticalDistance": vertical_distance,
                "interceptDistance": intercept_distance,
            }
        )
    threats.sort(key=lambda item: (item["interceptDistance"], item["horizontalDistance"]))
    return {
        "unsafe": bool(threats),
        "nearestThreat": threats[0] if threats else None,
        "threats": threats[:3],
    }


def assess_emergency_hole_escape_threat(
    snapshot: dict[str, Any], target_cell: dict[str, Any]
) -> dict[str, Any]:
    """Reject a short escape drop whose landing lane is occupied or pinched by guards."""
    target_x = _to_int(target_cell.get("x"))
    target_y = _to_int(target_cell.get("y"))
    if target_x is None or target_y is None:
        return {"unsafe": True, "reason": "escape hole coordinates unavailable", "threats": []}

    threats = []
    for guard in snapshot.get("guards") or []:
        if not isinstance(guard, dict):
            continue
        guard_x = _to_int(guard.get("x"))
        guard_y = _to_int(guard.get("y"))
        if guard_x is None or guard_y is None:
            continue
        if guard_y not in {target_y, target_y + 1} or abs(guard_x - target_x) > 1:
            continue
        threats.append(
            {
                "id": guard.get("id"),
                "x": guard_x,
                "y": guard_y,
                "xOffset": _to_int(guard.get("xOffset")) or 0,
                "motion": str(guard.get("actionName") or "unknown"),
                "exactColumn": guard_x == target_x,
                "holeRow": guard_y == target_y,
            }
        )
    exact = any(item["exactColumn"] for item in threats)
    pinched = len(threats) >= 2
    hole_row_guard = any(item["holeRow"] for item in threats)
    adjacent_guard = any(not item["exactColumn"] for item in threats)
    return {
        "unsafe": exact or pinched or hole_row_guard or adjacent_guard,
        "reason": (
            "guard occupies or borders the open escape row"
            if hole_row_guard
            else "guard occupies the escape landing column"
            if exact
            else "guards cover both sides of the escape landing"
            if pinched
            else "adjacent landing-row guard can cross the escape lane"
            if adjacent_guard
            else None
        ),
        "threats": threats,
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
    nearest_guard = None
    nearby_guards = []
    for guard in guards:
        if not isinstance(guard, dict):
            continue
        guard_x = _to_int(guard.get("x"))
        guard_y = _to_int(guard.get("y"))
        if guard_x is None or guard_y is None:
            continue
        distance = abs(guard_x - runner_x) + abs(guard_y - runner_y)
        distances.append(distance)
        motion = str(guard.get("actionName") or "unknown")
        guard_info = {
            "id": guard.get("id"),
            "x": guard_x,
            "y": guard_y,
            "xOffset": _to_int(guard.get("xOffset")) or 0,
            "yOffset": _to_int(guard.get("yOffset")) or 0,
            "distance": distance,
            "risk": _guard_effective_risk(distance, motion),
            "relativeX": _direction_label(runner_x, guard_x),
            "relativeY": _vertical_label(runner_y, guard_y),
            "motion": motion,
            "hasGold": _to_int(guard.get("hasGold")) or 0,
        }
        guard_info["closing"] = (
            (guard_info["relativeX"] == "left" and guard_info["motion"] == "right")
            or (guard_info["relativeX"] == "right" and guard_info["motion"] == "left")
        )
        nearby_guards.append(guard_info)
        if nearest_guard is None or distance < nearest_guard["distance"]:
            nearest_guard = guard_info
        if guard_y == runner_y:
            side = _direction_label(runner_x, guard_x)
            same_row_distance = abs(guard_x - runner_x)
            info = {
                "x": guard_x,
                "distance": same_row_distance,
                "risk": _guard_effective_risk(same_row_distance, motion),
                "side": side,
                "motion": motion,
                "closing": (
                    (side == "left" and motion == "right")
                    or (side == "right" and motion == "left")
                ),
            }
            same_row.append(info)
            if nearest_same_row is None or info["distance"] < nearest_same_row["distance"]:
                nearest_same_row = info

    nearest = min(distances) if distances else None
    risk_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    pressure_guard = min(
        nearby_guards,
        key=lambda item: (
            -risk_order.get(str(item.get("risk")), 0),
            0 if item.get("relativeY") == "same" else 1,
            item["distance"],
        ),
        default=None,
    )
    risk = pressure_guard.get("risk") if pressure_guard else "low"
    return {
        "risk": risk,
        "nearestGuardDistance": nearest,
        "nearestGuard": nearest_guard,
        "pressureGuard": pressure_guard,
        "nearbyGuards": sorted(nearby_guards, key=lambda item: item["distance"])[:4],
        "sameRowGuards": sorted(same_row, key=lambda item: item["distance"])[:4],
        "nearestSameRowGuard": nearest_same_row,
        "runnerOnEdge": _is_edge(runner_x, width),
    }


def _guard_risk_for_distance(distance: int | None) -> str:
    if distance is None:
        return "low"
    if distance <= 1:
        return "critical"
    if distance <= 3:
        return "high"
    if distance <= 5:
        return "medium"
    return "low"


def _guard_effective_risk(distance: int | None, motion: str) -> str:
    if motion == "in_hole":
        return "low"
    return _guard_risk_for_distance(distance)
