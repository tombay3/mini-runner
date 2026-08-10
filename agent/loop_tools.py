from __future__ import annotations

from typing import Any

from .reasoning_tools import (
    DOWN_KEYCODE,
    LEFT_KEYCODE,
    RIGHT_KEYCODE,
    STOP_KEYCODE,
    UP_KEYCODE,
)


ENVIRONMENT_PROGRESS_KINDS = {
    "emergency_hold",
    "retreat_from_guard",
    "wait_for_floor_refill",
    "wait_for_guard_clearance",
    "wait_for_dig_completion",
    "wait_for_trap_resolution",
}

def build_loop_report(
    analysis: dict[str, Any], history: list[dict[str, Any]], window: int = 10
) -> dict[str, Any]:
    recent = [item for item in history[-window:] if isinstance(item, dict)]
    positions = collect_positions(recent)
    candidate_ids = collect_candidate_ids(recent)
    key_codes = collect_key_codes(recent)
    gold_counts = collect_gold_counts(recent)
    repeated_id = candidate_ids[-1] if candidate_ids else None
    repeated_kind = candidate_kind(repeated_id)
    repeated_progress = assess_repeated_candidate_progress(recent, repeated_id)
    same_candidate_streak = count_tail_equal(candidate_ids)
    environment_progress = repeated_kind in ENVIRONMENT_PROGRESS_KINDS

    report = empty_loop_report(
        positions=positions,
        candidate_ids=candidate_ids,
        key_codes=key_codes,
        gold_counts=gold_counts,
        repeated_progress=repeated_progress,
        same_candidate_streak=same_candidate_streak,
    )
    if len(positions) < 4:
        return report

    row_values = {y for _x, y in positions}
    x_values = [x for x, _y in positions]
    no_row_change = len(row_values) == 1
    no_gold_change = len(set(gold_counts)) <= 1 if gold_counts else True
    x_range = max(x_values) - min(x_values)
    direction_changes = count_direction_changes(key_codes)
    same_tile_streak = count_tail_equal(positions)
    stop_streak = count_tail_equal(key_codes) if key_codes[-1:] == [STOP_KEYCODE] else 0
    recent_horizontal_cycle = detect_recent_horizontal_cycle(positions, key_codes)
    horizontal_cycle = (
        no_row_change
        and no_gold_change
        and not environment_progress
        and repeated_kind != "retreat_from_guard"
        and not repeated_progress["madeProgress"]
        and not repeated_progress["targetReached"]
        and (
            (len(positions) >= 6 and x_range <= 4 and direction_changes >= 4)
            or recent_horizontal_cycle
        )
    )
    vertical_cycle = detect_vertical_cycle(
        positions=positions,
        key_codes=key_codes,
        candidate_ids=candidate_ids,
        no_gold_change=no_gold_change,
        primary_target=dict_value(analysis.get("primaryProgressTarget")),
        movement=dict_value(analysis.get("movement")),
    )
    stationary_repeat = (
        no_gold_change
        and no_row_change
        and repeated_id is not None
        and (
            not environment_progress
            or (
                repeated_kind == "emergency_hold"
                and same_tile_streak >= 6
                and any(
                    candidate_kind(candidate_id) == "wait_or_stop"
                    for candidate_id in candidate_ids[-6:]
                )
            )
        )
        and (
            (repeated_kind == "route_access_dig" and same_candidate_streak >= 2)
            or (repeated_kind == "wait_or_stop" and stop_streak >= 3)
            or (
                same_candidate_streak >= 4
                and not repeated_progress["madeProgress"]
                and not repeated_progress["targetReached"]
            )
            or same_tile_streak >= 6
        )
    )

    loop_type = None
    if vertical_cycle["detected"]:
        loop_type = "vertical_cycle"
    elif horizontal_cycle:
        loop_type = "horizontal_cycle"
    elif stationary_repeat:
        loop_type = "stationary_repeat"

    report["evidence"].update(
        {
            "xRange": x_range,
            "directionChanges": direction_changes,
            "sameTileStreak": same_tile_streak,
            "noRowChange": no_row_change,
            "noGoldChange": no_gold_change,
        }
    )
    if loop_type is None:
        return report

    report.update(
        {
            "active": True,
            "type": loop_type,
            "target": (
                find_cycle_target(analysis, positions)
                if loop_type == "horizontal_cycle"
                else None
            ),
        }
    )
    suppress_ids: list[str] = []
    suppress_kinds: list[str] = []
    suppress_directions: list[str] = []
    preserve_safety_retreat = repeated_kind == "retreat_from_guard"
    if repeated_id and not preserve_safety_retreat:
        suppress_ids.append(repeated_id)
    suppress_kinds.append("wait_or_stop")
    if loop_type == "vertical_cycle":
        suppress_directions = blocked_vertical_directions(vertical_cycle)
    report["suppress"] = {
        "candidateIds": suppress_ids,
        "candidateKinds": suppress_kinds,
        "directions": suppress_directions,
    }
    report["vertical"] = {
        "ladderX": vertical_cycle.get("ladderX"),
        "preferredDirection": vertical_cycle.get("preferredDirection"),
        "exitDirection": vertical_cycle.get("exitDirection"),
        "climbDirections": vertical_cycle.get("climbDirections", []),
    }
    return report


def candidate_suppression_reason(
    candidate: dict[str, Any], loop_report: dict[str, Any]
) -> str | None:
    if not loop_report.get("active"):
        return None
    suppress = dict_value(loop_report.get("suppress"))
    candidate_id = candidate.get("id")
    kind = candidate.get("kind")
    if candidate_id in set(suppress.get("candidateIds") or []):
        return f"repeats {loop_report.get('type')} candidate {candidate_id}"
    if kind in set(suppress.get("candidateKinds") or []):
        return f"candidate kind {kind} prolongs {loop_report.get('type')}"
    direction = action_direction(candidate)
    if kind == "climb_ladder" and direction in set(suppress.get("directions") or []):
        return f"ladder direction {direction} repeats {loop_report.get('type')}"
    return None


def record_suppressed_candidate(
    loop_report: dict[str, Any], candidate: dict[str, Any], reason: str
) -> None:
    suppressed = loop_report.setdefault("suppressedCandidates", [])
    candidate_id = candidate.get("id")
    if any(item.get("id") == candidate_id for item in suppressed if isinstance(item, dict)):
        return
    suppressed.append(
        {
            "id": candidate_id,
            "kind": candidate.get("kind"),
            "direction": action_direction(candidate),
            "reason": reason,
        }
    )


def empty_loop_report(
    *,
    positions: list[tuple[int, int]],
    candidate_ids: list[str],
    key_codes: list[int],
    gold_counts: list[int],
    repeated_progress: dict[str, Any],
    same_candidate_streak: int,
) -> dict[str, Any]:
    repeated_id = candidate_ids[-1] if candidate_ids else None
    return {
        "active": False,
        "type": None,
        "evidence": {
            "positions": positions[-8:],
            "candidateIds": candidate_ids[-8:],
            "keyCodes": key_codes[-8:],
            "sameCandidateStreak": same_candidate_streak,
            "repeatedCandidateId": repeated_id,
            "target": repeated_progress["target"],
            "startDistance": repeated_progress["startDistance"],
            "endDistance": repeated_progress["endDistance"],
            "targetProgress": repeated_progress["madeProgress"],
            "targetReached": repeated_progress["targetReached"],
            "noGoldChange": len(set(gold_counts)) <= 1 if gold_counts else True,
        },
        "suppress": {"candidateIds": [], "candidateKinds": [], "directions": []},
        "suppressedCandidates": [],
        "target": None,
        "vertical": {
            "ladderX": None,
            "preferredDirection": None,
            "exitDirection": None,
            "climbDirections": [],
        },
    }


def detect_recent_horizontal_cycle(
    positions: list[tuple[int, int]], key_codes: list[int]
) -> bool:
    if len(positions) < 6:
        return False
    tail_positions = positions[-6:]
    if len({y for _x, y in tail_positions}) != 1:
        return False
    x_values = [x for x, _y in tail_positions]
    return bool(
        max(x_values) - min(x_values) <= 4
        and abs(x_values[-1] - x_values[0]) <= 2
        and count_direction_changes(key_codes[-6:]) >= 4
    )


def detect_vertical_cycle(
    *,
    positions: list[tuple[int, int]],
    key_codes: list[int],
    candidate_ids: list[str],
    no_gold_change: bool,
    primary_target: dict[str, Any],
    movement: dict[str, Any],
) -> dict[str, Any]:
    if len(positions) < 6 or not no_gold_change:
        return {"detected": False}
    x_values = {x for x, _y in positions}
    y_values = [y for _x, y in positions]
    vertical_actions = [
        (key, candidate_id)
        for key, candidate_id in zip(key_codes, candidate_ids, strict=False)
        if key in {UP_KEYCODE, DOWN_KEYCODE}
    ]
    vertical_keys = [key for key, _candidate_id in vertical_actions]
    if len(x_values) != 1 or len(set(y_values)) not in {2, 3} or len(vertical_keys) < 6:
        return {"detected": False}
    direction_runs = collapse_direction_runs(vertical_keys)
    alternating_runs = len(direction_runs) >= 4 and all(
        direction_runs[index] != direction_runs[index - 1]
        for index in range(1, len(direction_runs))
    )
    ladder_actions = bool(candidate_ids) and all(
        candidate_kind(candidate_id)
        in {"climb_ladder", "descend_route", "retreat_from_guard"}
        for candidate_id in candidate_ids[-6:]
    )
    if not alternating_runs or not ladder_actions:
        return {"detected": False}
    climb_directions = sorted(
        {
            "up" if key == UP_KEYCODE else "down"
            for key, candidate_id in vertical_actions[-6:]
            if candidate_kind(candidate_id) == "climb_ladder"
        }
    )
    current_y = positions[-1][1]
    target_y = to_int(primary_target.get("y"))
    preferred = "up" if target_y is not None and target_y < current_y else "down" if target_y is not None and target_y > current_y else None
    direction = primary_target.get("direction")
    exit_direction = (
        direction
        if direction in {"left", "right"}
        and movement.get("canMoveLeft" if direction == "left" else "canMoveRight")
        else None
    )
    return {
        "detected": True,
        "ladderX": next(iter(x_values)),
        "preferredDirection": preferred,
        "exitDirection": exit_direction,
        "climbDirections": climb_directions,
    }


def blocked_vertical_directions(vertical: dict[str, Any]) -> list[str]:
    climb_directions = [
        direction
        for direction in vertical.get("climbDirections") or []
        if direction in {"down", "up"}
    ]
    if climb_directions:
        return climb_directions
    if vertical.get("exitDirection"):
        return ["down", "up"]
    preferred = vertical.get("preferredDirection")
    if preferred == "up":
        return ["down"]
    if preferred == "down":
        return ["up"]
    return []


def collapse_direction_runs(key_codes: list[int]) -> list[int]:
    runs: list[int] = []
    for key_code in key_codes:
        if not runs or runs[-1] != key_code:
            runs.append(key_code)
    return runs


def assess_repeated_candidate_progress(
    recent: list[dict[str, Any]], candidate_id: str | None
) -> dict[str, Any]:
    target = candidate_target(candidate_id)
    result = {
        "target": target,
        "startDistance": None,
        "endDistance": None,
        "madeProgress": False,
        "targetReached": False,
    }
    if not target or not candidate_id:
        return result
    repeated_tail: list[dict[str, Any]] = []
    for item in reversed(recent):
        if item.get("candidateId") != candidate_id:
            break
        repeated_tail.append(item)
    repeated_tail.reverse()
    start = runner_position(dict_value(repeated_tail[0].get("before"))) if repeated_tail else None
    end = runner_position(dict_value(repeated_tail[-1].get("after"))) if repeated_tail else None
    if start is None or end is None:
        return result
    start_distance = candidate_distance(candidate_id, start, target)
    end_distance = candidate_distance(candidate_id, end, target)
    result.update(
        {
            "startDistance": start_distance,
            "endDistance": end_distance,
            "madeProgress": end_distance < start_distance,
            "targetReached": end == target,
        }
    )
    return result


def find_cycle_target(
    analysis: dict[str, Any], positions: list[tuple[int, int]]
) -> dict[str, Any] | None:
    xs = [x for x, _y in positions]
    row = positions[-1][1]
    for kind, items in (
        ("ladder", analysis.get("rowLadders") or []),
        ("gold", analysis.get("nearestGold") or []),
    ):
        for item in items:
            x = to_int(item.get("x"))
            y = to_int(item.get("y"))
            if x is not None and y == row and min(xs) <= x <= max(xs):
                return {"x": x, "y": y, "kind": kind}
    return None


def candidate_target(candidate_id: str | None) -> tuple[int, int] | None:
    kind = candidate_kind(candidate_id)
    if kind not in {
        "align_ladder",
        "classic_gold_route",
        "collect_current_tile_gold",
        "collect_same_row_gold",
        "descend_route",
        "exit_ladder_route",
    }:
        return None
    prefix = f"{kind}_"
    if not candidate_id or not candidate_id.startswith(prefix):
        return None
    parts = candidate_id[len(prefix) :].split("_")
    x = to_int(parts[0]) if len(parts) >= 2 else None
    y = to_int(parts[1]) if len(parts) >= 2 else None
    return (x, y) if x is not None and y is not None else None


def candidate_distance(
    candidate_id: str, position: tuple[int, int], target: tuple[int, int]
) -> int:
    if candidate_kind(candidate_id) == "align_ladder" and position[1] == target[1]:
        return abs(position[0] - target[0])
    return abs(position[0] - target[0]) + abs(position[1] - target[1])


def candidate_kind(candidate_id: str | None) -> str | None:
    if not candidate_id:
        return None
    known_kinds = [
        "collect_same_row_gold",
        "collect_current_tile_gold",
        "route_access_follow",
        "route_access_dig",
        "retreat_from_guard",
        "escape_through_open_hole",
        "evade_edge_ladder",
        "evade_open_hole",
        "exit_ladder_route",
        "defensive_dig",
        "climb_ladder",
        "align_ladder",
        "descend_route",
        "wait_or_stop",
        "wait_for_guard_clearance",
        "wait_for_floor_refill",
        "wait_for_dig_completion",
        "wait_for_trap_resolution",
        "emergency_hold",
        "classic_gold_route",
        "god_mode_progress",
    ]
    for kind in known_kinds:
        if candidate_id == kind or candidate_id.startswith(f"{kind}_"):
            return kind
    return candidate_id.rsplit("_", 1)[0]


def action_direction(candidate: dict[str, Any]) -> str | None:
    key_code = to_int(dict_value(candidate.get("firstAction")).get("keyCode"))
    return {
        LEFT_KEYCODE: "left",
        RIGHT_KEYCODE: "right",
        UP_KEYCODE: "up",
        DOWN_KEYCODE: "down",
        STOP_KEYCODE: "stop",
    }.get(key_code)


def collect_positions(recent: list[dict[str, Any]]) -> list[tuple[int, int]]:
    positions: list[tuple[int, int]] = []
    for item in recent:
        position = runner_position(dict_value(item.get("after")))
        if position is not None:
            positions.append(position)
    return positions


def collect_gold_counts(recent: list[dict[str, Any]]) -> list[int]:
    values: list[int] = []
    for item in recent:
        value = to_int(dict_value(item.get("after")).get("goldCount"))
        if value is not None:
            values.append(value)
    return values


def collect_candidate_ids(recent: list[dict[str, Any]]) -> list[str]:
    return [item["candidateId"] for item in recent if isinstance(item.get("candidateId"), str)]


def collect_key_codes(recent: list[dict[str, Any]]) -> list[int]:
    return [value for item in recent if (value := to_int(item.get("keyCode"))) is not None]


def runner_position(state: dict[str, Any]) -> tuple[int, int] | None:
    runner = dict_value(state.get("runner"))
    x = to_int(runner.get("x"))
    y = to_int(runner.get("y"))
    return (x, y) if x is not None and y is not None else None


def count_direction_changes(key_codes: list[int]) -> int:
    horizontal = [key for key in key_codes if key in {LEFT_KEYCODE, RIGHT_KEYCODE}]
    return sum(
        1 for index in range(1, len(horizontal)) if horizontal[index] != horizontal[index - 1]
    )


def count_tail_equal(items: list[Any]) -> int:
    if not items:
        return 0
    tail = items[-1]
    count = 0
    for item in reversed(items):
        if item != tail:
            break
        count += 1
    return count


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
