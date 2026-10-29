from __future__ import annotations

from typing import Any

from .reasoning_tools import (
    DOWN_KEYCODE,
    LEFT_KEYCODE,
    RIGHT_KEYCODE,
    STOP_KEYCODE,
    UP_KEYCODE,
)


KNOWN_CANDIDATE_KINDS = (
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
    "wait_and_recheck",
    "wait_for_guard_clearance",
    "wait_for_floor_refill",
    "wait_for_dig_completion",
    "wait_for_trap_resolution",
    "emergency_hold",
    "god_mode_progress",
    "low_risk_horizontal_progress",
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
    # A gap breaks the evidence window: skipping it could join unrelated actions
    # or manufacture a cycle across an unobserved transition.
    recent, positions, candidate_ids, key_codes, gold_counts = [], [], [], [], []
    for item in reversed(history[-window:]):
        if not isinstance(item, dict):
            break
        candidate_id = item.get("candidateId")
        key_code = to_int(item.get("keyCode"))
        after = dict_value(item.get("after"))
        position = runner_position(after)
        gold_count = to_int(after.get("goldCount"))
        if not isinstance(candidate_id, str) or key_code is None or position is None or gold_count is None:
            break
        recent.append(item)
        positions.append(position)
        candidate_ids.append(candidate_id)
        key_codes.append(key_code)
        gold_counts.append(gold_count)
    for values in (recent, positions, candidate_ids, key_codes, gold_counts):
        values.reverse()
    repeated_id = candidate_ids[-1] if candidate_ids else None
    candidate_kinds = [candidate_kind(candidate_id) for candidate_id in candidate_ids]
    repeated_kind = candidate_kinds[-1] if candidate_kinds else None
    repeated_progress = assess_repeated_candidate_progress(recent, repeated_id)
    same_candidate_streak = count_tail_equal(candidate_ids)
    environment_progress = repeated_kind in ENVIRONMENT_PROGRESS_KINDS
    environment_progress_count = sum(
        kind in ENVIRONMENT_PROGRESS_KINDS for kind in candidate_kinds
    )
    environment_progress_dominated = bool(
        environment_progress_count >= 3
        and environment_progress_count * 2 > len(candidate_ids)
    )

    report = empty_loop_report(
        positions=positions,
        candidate_ids=candidate_ids,
        key_codes=key_codes,
        gold_counts=gold_counts,
        repeated_progress=repeated_progress,
        same_candidate_streak=same_candidate_streak,
    )
    if dict_value(analysis.get("activeDig")).get("active"):
        return report
    if len(positions) < 4:
        return report

    row_values = {y for _x, y in positions}
    x_values = [x for x, _y in positions]
    no_row_change = len(row_values) == 1
    no_gold_change = report["evidence"]["noGoldChange"]
    x_range = max(x_values) - min(x_values)
    direction_changes = count_direction_changes(key_codes)
    same_tile_streak = count_tail_equal(positions)
    stop_streak = count_tail_equal(key_codes) if key_codes[-1:] == [STOP_KEYCODE] else 0
    recent_horizontal_cycle = detect_recent_horizontal_cycle(positions, key_codes)
    safety_retreat_count = sum(
        kind == "retreat_from_guard" for kind in candidate_kinds
    )
    safety_retreat_dominated = bool(
        safety_retreat_count >= 3
        and safety_retreat_count * 2 > len(candidate_ids)
    )
    horizontal_cycle = (
        no_gold_change
        and not environment_progress
        and not safety_retreat_dominated
        and (
            (no_row_change and len(positions) >= 6 and x_range <= 4 and direction_changes >= 4)
            or recent_horizontal_cycle
        )
    )
    vertical_cycle = detect_vertical_cycle(
        positions=positions,
        key_codes=key_codes,
        candidate_ids=candidate_ids,
        no_gold_change=no_gold_change,
        gold_target=dict_value(analysis.get("goldTarget")),
        movement=dict_value(analysis.get("movement")),
    )
    stationary_repeat = (
        no_gold_change and no_row_change and repeated_id is not None
        and _is_stationary_repeat(
            candidate_kinds=candidate_kinds,
            environment_progress_dominated=environment_progress_dominated,
            same_tile_streak=same_tile_streak,
            same_candidate_streak=same_candidate_streak,
            stop_streak=stop_streak,
            repeated_progress=repeated_progress,
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
            "safetyRetreatCount": safety_retreat_count,
            "safetyRetreatDominated": safety_retreat_dominated,
            "environmentProgressCount": environment_progress_count,
            "environmentProgressDominated": environment_progress_dominated,
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
    if loop_type == "horizontal_cycle":
        # Suppression needs subtile motion; public target-distance observations
        # and loop detection intentionally remain tile-based.
        report["evidence"]["horizontalOffsetProgress"] = (
            _made_horizontal_offset_progress(recent, repeated_id)
        )
    preserve_horizontal_progress = bool(
        loop_type == "horizontal_cycle"
        and (
            repeated_progress["madeProgress"]
            or report["evidence"].get("horizontalOffsetProgress")
        )
        and not repeated_progress["targetReached"]
    )
    if repeated_id and not preserve_safety_retreat and not preserve_horizontal_progress:
        suppress_ids.append(repeated_id)
    suppress_kinds.append("wait_and_recheck")
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
        "verticalDirections": vertical_cycle.get("verticalDirections", []),
    }
    return report


def _is_stationary_repeat(
    *, candidate_kinds: list[str | None], environment_progress_dominated: bool,
    same_tile_streak: int, same_candidate_streak: int, stop_streak: int,
    repeated_progress: dict[str, Any],
) -> bool:
    repeated_kind = candidate_kinds[-1]
    emergency_repeat = (
        repeated_kind == "emergency_hold"
        and same_tile_streak >= 6
        and "wait_and_recheck" in candidate_kinds[-6:]
    )
    if not emergency_repeat and (
        repeated_kind in ENVIRONMENT_PROGRESS_KINDS or environment_progress_dominated
    ):
        return False
    return (
        (repeated_kind == "route_access_dig" and same_candidate_streak >= 2)
        or (repeated_kind == "wait_and_recheck" and stop_streak >= 3)
        or (
            same_candidate_streak >= 4
            and not repeated_progress["madeProgress"]
            and not repeated_progress["targetReached"]
        )
        or same_tile_streak >= 6
    )


def candidate_suppression_reason(
    candidate: dict[str, Any], loop_report: dict[str, Any]
) -> str | None:
    if not loop_report.get("active"):
        return None
    suppress = dict_value(loop_report.get("suppress"))
    candidate_id = candidate.get("id")
    kind = candidate.get("kind")
    # A loop must not remove the last bounded safety action.  Emergency hold
    # is the generator's final escape hatch when ordinary actions are unsafe;
    # suppressing it can turn a recoverable wait into an empty candidate set.
    if kind == "emergency_hold":
        return None
    evidence = dict_value(loop_report.get("evidence"))
    if (
        loop_report.get("type") == "horizontal_cycle"
        and candidate_id == evidence.get("repeatedCandidateId")
        and (
            evidence.get("targetProgress") is True
            or evidence.get("horizontalOffsetProgress") is True
        )
        and evidence.get("targetReached") is not True
    ):
        return None
    if candidate_id in set(suppress.get("candidateIds") or []):
        return f"repeats {loop_report.get('type')} candidate {candidate_id}"
    if kind in set(suppress.get("candidateKinds") or []):
        return f"candidate kind {kind} prolongs {loop_report.get('type')}"
    direction = action_direction(candidate)
    if (
        loop_report.get("type") == "horizontal_cycle"
        and kind not in ENVIRONMENT_PROGRESS_KINDS
        and direction in {"left", "right"}
    ):
        target = candidate_target(candidate_id)
        loop_target = loop_report.get("target") or dict_value(
            loop_report.get("evidence")
        ).get("target")
        if isinstance(loop_target, dict):
            loop_target = (to_int(loop_target.get("x")), to_int(loop_target.get("y")))
        if (
            target is not None
            and isinstance(loop_target, (list, tuple))
            and tuple(loop_target) == target
        ):
            return (
                f"same target ({target[0]},{target[1]}) as suppressed "
                "horizontal_cycle route"
            )
    if (
        loop_report.get("type") == "vertical_cycle"
        and kind in {"climb_ladder", "descend_route"}
        and direction in set(suppress.get("directions") or [])
    ):
        return f"vertical direction {direction} repeats {loop_report.get('type')}"
    return None


def predicted_horizontal_return_target(
    loop_report: dict[str, Any],
) -> tuple[int, int] | None:
    """Return A for an existing horizontal-cycle target sequence A-B-A-B."""
    if loop_report.get("type") != "horizontal_cycle":
        return None
    evidence = dict_value(loop_report.get("evidence"))
    if evidence.get("noGoldChange") is not True or evidence.get("noRowChange") is not True:
        return None
    candidate_ids = evidence.get("candidateIds") or []
    key_codes = evidence.get("keyCodes") or []
    if len(candidate_ids) != len(key_codes):
        return None
    target_runs: list[tuple[int, int]] = []
    for candidate_id, key_code in zip(candidate_ids, key_codes, strict=True):
        target = candidate_target(candidate_id)
        if key_code not in {LEFT_KEYCODE, RIGHT_KEYCODE} or target is None:
            target_runs = []
            continue
        if not target_runs or target_runs[-1] != target:
            target_runs.append(target)
    if len(target_runs) < 4:
        return None
    first, second, third, fourth = target_runs[-4:]
    if first != third or second != fourth or first == second:
        return None
    return first


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
            "verticalDirections": [],
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
    gold_target: dict[str, Any],
    movement: dict[str, Any],
) -> dict[str, Any]:
    if len(positions) < 6 or not no_gold_change:
        return {"detected": False}
    x_values = {x for x, _y in positions}
    y_values = [y for _x, y in positions]
    current_y = positions[-1][1]
    if y_values.count(current_y) < 2:
        return {"detected": False}
    vertical_actions = [
        (key, candidate_id)
        for key, candidate_id in zip(key_codes, candidate_ids, strict=False)
        if key in {UP_KEYCODE, DOWN_KEYCODE}
    ]
    vertical_keys = [key for key, _candidate_id in vertical_actions]
    if len(x_values) != 1 or len(set(y_values)) not in {2, 3} or len(vertical_keys) < 6:
        return {"detected": False}
    direction_runs = collapse_direction_runs(vertical_keys)
    alternating_runs = len(direction_runs) >= 4
    ladder_actions = bool(candidate_ids) and all(
        candidate_kind(candidate_id)
        in {"climb_ladder", "descend_route", "retreat_from_guard"}
        for candidate_id in candidate_ids[-6:]
    )
    if not alternating_runs or not ladder_actions:
        return {"detected": False}
    vertical_directions = sorted(
        {
            "up" if key == UP_KEYCODE else "down"
            for key, candidate_id in vertical_actions[-6:]
            if candidate_kind(candidate_id) in {"climb_ladder", "descend_route"}
        }
    )
    target_y = to_int(gold_target.get("y"))
    preferred = "up" if target_y is not None and target_y < current_y else "down" if target_y is not None and target_y > current_y else None
    direction = gold_target.get("direction")
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
        "verticalDirections": vertical_directions,
    }


def blocked_vertical_directions(vertical: dict[str, Any]) -> list[str]:
    vertical_directions = [
        direction
        for direction in vertical.get("verticalDirections") or []
        if direction in {"down", "up"}
    ]
    if vertical_directions:
        return vertical_directions
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
    start_distance = candidate_distance(start, target)
    end_distance = candidate_distance(end, target)
    result.update(
        {
            "startDistance": start_distance,
            "endDistance": end_distance,
            "madeProgress": end_distance < start_distance,
            "targetReached": end == target,
        }
    )
    return result


def _made_horizontal_offset_progress(
    recent: list[dict[str, Any]], candidate_id: str | None
) -> bool:
    target = candidate_target(candidate_id)
    if target is None:
        return False
    tail = []
    for item in reversed(recent):
        if item.get("candidateId") != candidate_id:
            break
        if item.get("keyCode") not in {LEFT_KEYCODE, RIGHT_KEYCODE}:
            return False
        tail.append(item)
    if not tail:
        return False
    before = dict_value(dict_value(tail[-1].get("before")).get("runner"))
    after = dict_value(dict_value(tail[0].get("after")).get("runner"))
    # Missing offsets must not manufacture progress or weaken suppression.
    if any(
        type(actor.get(key)) is not int
        for actor in (before, after)
        for key in ("x", "y", "xOffset", "yOffset")
    ):
        return False
    if (
        before["y"] != target[1] or after["y"] != target[1]
        or before["yOffset"] != after["yOffset"]
    ):
        return False
    start = abs((target[0] - before["x"]) * 40 - before["xOffset"])
    end = abs((target[0] - after["x"]) * 40 - after["xOffset"])
    return end < start


def find_cycle_target(
    analysis: dict[str, Any], positions: list[tuple[int, int]]
) -> dict[str, Any] | None:
    xs = [x for x, _y in positions]
    row = positions[-1][1]
    min_x, max_x = min(xs), max(xs)
    for kind, items in (
        ("ladder", analysis.get("rowLadders") or []),
        ("gold", analysis.get("nearestGold") or []),
    ):
        for item in items:
            x = to_int(item.get("x"))
            y = to_int(item.get("y"))
            if x is not None and y == row and min_x <= x <= max_x:
                return {"x": x, "y": y, "kind": kind}
    return None


def candidate_target(candidate_id: str | None) -> tuple[int, int] | None:
    kind = candidate_kind(candidate_id)
    if kind not in {
        "align_ladder",
        "collect_current_tile_gold",
        "collect_same_row_gold",
        "descend_route",
        "exit_ladder_route",
        "god_mode_progress",
        "low_risk_horizontal_progress",
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
    position: tuple[int, int], target: tuple[int, int]
) -> int:
    return abs(position[0] - target[0]) + abs(position[1] - target[1])


def candidate_kind(candidate_id: str | None) -> str | None:
    if not candidate_id:
        return None
    for kind in KNOWN_CANDIDATE_KINDS:
        if candidate_id == kind or candidate_id.startswith(f"{kind}_"):
            return kind
    return candidate_id.rsplit("_", 1)[0]


def action_direction(candidate: dict[str, Any]) -> str | None:
    key_code = to_int(dict_value(candidate.get("action")).get("keyCode"))
    return {
        LEFT_KEYCODE: "left",
        RIGHT_KEYCODE: "right",
        UP_KEYCODE: "up",
        DOWN_KEYCODE: "down",
        STOP_KEYCODE: "stop",
    }.get(key_code)


def runner_coordinates(
    runner: dict[str, Any], *, include_offsets: bool = False,
) -> tuple[int | None, ...]:
    fields = ("x", "y", "xOffset", "yOffset") if include_offsets else ("x", "y")
    return tuple(to_int(runner.get(field)) for field in fields)


def runner_position(state: dict[str, Any]) -> tuple[int, int] | None:
    runner = dict_value(state.get("runner"))
    x, y = runner_coordinates(runner)
    return (x, y) if x is not None and y is not None else None


def count_direction_changes(key_codes: list[int]) -> int:
    horizontal = [key for key in key_codes if key in {LEFT_KEYCODE, RIGHT_KEYCODE}]
    return max(0, len(collapse_direction_runs(horizontal)) - 1)


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
