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


def _get_active_grid(snapshot: dict[str, Any]) -> list[str]:
    grid = _get_grid(snapshot, "grid")
    if grid:
        return grid
    return _get_grid(snapshot, "baseGrid")


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


def find_nearest_gold_candidates(snapshot: dict[str, Any], limit: int = 4) -> list[dict[str, Any]]:
    runner = _get_runner(snapshot)
    runner_x = _to_int(runner.get("x"))
    runner_y = _to_int(runner.get("y"))
    if runner_x is None or runner_y is None:
        return []

    rows = _get_active_grid(snapshot)
    candidates = []
    for position in _scan_positions(rows, {"$"}):
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

    grids = [_get_grid(snapshot, "grid"), _get_grid(snapshot, "baseGrid")]
    seen = set()
    ladders = []
    for rows in grids:
        if runner_y < 0 or runner_y >= len(rows):
            continue
        row = rows[runner_y]
        for x, char in enumerate(row):
            if char not in {"H", "S"}:
                continue
            key = (x, char)
            if key in seen:
                continue
            seen.add(key)
            ladders.append(
                {
                    "x": x,
                    "y": runner_y,
                    "distance": abs(x - runner_x),
                    "direction": _direction_label(runner_x, x),
                    "visible": char == "H",
                    "tile": char,
                }
            )

    ladders.sort(key=lambda item: (0 if item["visible"] else 1, item["distance"], item["x"]))
    return ladders[: max(1, limit)]


def assess_guard_risk(snapshot: dict[str, Any]) -> dict[str, Any]:
    runner = _get_runner(snapshot)
    guards = snapshot.get("guards") or []
    grid = _get_active_grid(snapshot)
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
    grid_width = _grid_width(_get_active_grid(snapshot))

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

    no_progress_signals = not vertical_recent and not dig_recent
    stalled = bool(recent) and no_progress_signals and (
        repeated_same_direction or oscillating or edge_pressure or (stop_recent and same_state_streak)
    )

    return {
        "stalled": stalled,
        "recentActionCount": len(recent),
        "dominantDirection": dominant_direction,
        "dominantCount": dominant_count,
        "oscillating": oscillating,
        "edgePressure": edge_pressure,
        "edgeDirection": edge_direction,
        "rowChangeLikelyRecent": vertical_recent,
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
    stall = detect_progress_stall(snapshot, history)

    options = []
    same_row_gold = [item for item in nearest_gold if item["sameRow"]]
    visible_ladders = [item for item in row_ladders if item["visible"]]

    if risk["risk"] not in {"critical", "high"}:
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
        "stallDetected": stall["stalled"],
        "options": options[: max(1, limit)],
    }


def build_reasoning_tools(snapshot: dict[str, Any], history: list[dict[str, Any]]) -> list:
    runner = _get_runner(snapshot)
    guards = snapshot.get("guards") or []
    grid = _get_active_grid(snapshot)

    def summarize_snapshot() -> dict[str, Any]:
        """Summarize the current board state, runner position, guard pressure, and remaining goal state."""

        guard_positions = [{"x": guard.get("x"), "y": guard.get("y")} for guard in guards[:6]]
        gold_tiles = sum(row.count("$") for row in grid if isinstance(row, str))
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
        """List visible ladder opportunities on the runner row for safe upward progress."""

        return {"ladders": find_row_ladders(snapshot, limit=max(1, int(limit)))}

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

        if snapshot.get("goldComplete"):
            objective = "reach_exit_ladder"
            detail = "All gold is collected. Move toward the revealed exit path."
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
        detect_progress_stall_tool,
        assess_guard_risk_tool,
        assess_safe_progress_options_tool,
        suggest_subgoal,
        evaluate_last_action,
    ]
