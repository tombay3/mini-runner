from __future__ import annotations

from typing import Any

from .reasoning_tools import (
    DIG_LEFT_KEYCODE,
    DIG_RIGHT_KEYCODE,
    DOWN_KEYCODE,
    LEFT_KEYCODE,
    RIGHT_KEYCODE,
    STOP_KEYCODE,
    UP_KEYCODE,
)


def build_stall_report(
    analysis: dict[str, Any], history: list[dict[str, Any]], window: int = 10
) -> dict[str, Any]:
    recent = [item for item in history[-window:] if isinstance(item, dict)]
    positions = collect_positions(recent)
    gold_counts = collect_gold_counts(recent)
    candidate_ids = collect_candidate_ids(recent)
    key_codes = collect_key_codes(recent)

    if len(positions) < 4:
        return base_report(
            positions=positions,
            candidate_ids=candidate_ids,
            key_codes=key_codes,
            gold_counts=gold_counts,
        )

    row_values = {y for _x, y in positions}
    x_values = [x for x, _y in positions]
    x_range = max(x_values) - min(x_values)
    direction_changes = count_direction_changes(key_codes)
    no_row_change = len(row_values) == 1
    no_gold_change = len(set(gold_counts)) <= 1 if gold_counts else True
    same_tile_streak = count_tail_equal(positions)
    same_candidate_streak = count_tail_equal(candidate_ids)
    stop_streak = count_tail_equal(key_codes) if key_codes and key_codes[-1] == STOP_KEYCODE else 0
    repeated_candidate_id = candidate_ids[-1] if candidate_ids else None
    repeated_kind = candidate_kind(repeated_candidate_id)
    gold_complete = bool(analysis.get("goldComplete"))
    route_access = dict_value(analysis.get("routeAccess"))
    ladder = dict_value(analysis.get("ladder"))
    movement = dict_value(analysis.get("movement"))
    primary_target = dict_value(analysis.get("primaryProgressTarget"))

    bounded_horizontal_loop = (
        no_row_change and no_gold_change and len(positions) >= 6 and x_range <= 4 and direction_changes >= 4
    )
    vertical_ladder_loop = detect_vertical_ladder_loop(
        positions=positions,
        key_codes=key_codes,
        candidate_ids=candidate_ids,
        no_gold_change=no_gold_change,
        primary_target=primary_target,
        movement=movement,
    )
    same_candidate_no_progress = (
        no_gold_change and no_row_change and same_candidate_streak >= 4 and repeated_candidate_id is not None
    )
    same_tile_no_progress = no_gold_change and same_tile_streak >= 6 and repeated_candidate_id is not None
    route_access_loop = (
        no_gold_change
        and no_row_change
        and repeated_kind == "route_access_dig"
        and same_candidate_streak >= 2
    )
    exit_ladder_loop = (
        gold_complete
        and no_row_change
        and (
            bounded_horizontal_loop
            or repeated_kind in {"exit_ladder_route", "align_ladder", "godmode_progress"}
            and same_candidate_streak >= 3
        )
    )
    wait_loop = no_gold_change and no_row_change and (stop_streak >= 3 or repeated_kind == "wait_or_stop")

    stall_type = None
    if exit_ladder_loop:
        stall_type = "exit_ladder_loop"
    elif vertical_ladder_loop["detected"]:
        stall_type = "vertical_ladder_oscillation"
    elif route_access_loop:
        stall_type = "route_access_loop"
    elif wait_loop:
        stall_type = "wait_loop"
    elif bounded_horizontal_loop:
        stall_type = "horizontal_oscillation"
    elif same_candidate_no_progress:
        stall_type = "same_candidate_no_progress"
    elif same_tile_no_progress:
        stall_type = "same_tile_no_progress"

    severity = "stalled" if stall_type else "watch" if bounded_horizontal_loop or same_candidate_streak >= 3 else "none"
    blocked_ids, blocked_kinds = blocked_candidates_for(stall_type, repeated_candidate_id, repeated_kind)
    blocked_directions = blocked_ladder_directions_for(stall_type, vertical_ladder_loop)
    preferred_kinds = preferred_recovery_kinds(stall_type, gold_complete, route_access, ladder)
    target = find_oscillation_target(analysis, positions) if bounded_horizontal_loop else None

    return {
        "stalled": severity == "stalled",
        "severity": severity,
        "type": stall_type,
        "reason": human_reason(stall_type),
        "phase": "exit" if gold_complete else "collect_gold",
        "recentPositions": positions[-8:],
        "recentCandidateIds": candidate_ids[-8:],
        "recentKeyCodes": key_codes[-8:],
        "recentXRange": x_range,
        "directionChanges": direction_changes,
        "noRowChange": no_row_change,
        "noGoldChange": no_gold_change,
        "sameTileStreak": same_tile_streak,
        "sameCandidateStreak": same_candidate_streak,
        "repeatedCandidateId": repeated_candidate_id,
        "repeatedCandidateKind": repeated_kind,
        "blockedCandidateId": blocked_ids[0] if blocked_ids else None,
        "blockedCandidateIds": blocked_ids,
        "blockedCandidateKinds": blocked_kinds,
        "blockedLadderDirections": blocked_directions,
        "preferredCandidateKinds": preferred_kinds,
        "oscillationTarget": target,
        "ladderX": vertical_ladder_loop.get("ladderX"),
        "recentYRange": vertical_ladder_loop.get("recentYRange"),
        "preferredVerticalDirection": vertical_ladder_loop.get("preferredVerticalDirection"),
        "ladderExitDirection": vertical_ladder_loop.get("exitDirection"),
        "recoveryHint": recovery_hint(stall_type, preferred_kinds, target),
    }


def is_candidate_blocked(candidate: dict[str, Any], stall_report: dict[str, Any]) -> tuple[bool, str | None]:
    if stall_report.get("severity") != "stalled":
        return False, None
    candidate_id = candidate.get("id")
    kind = candidate.get("kind")
    blocked_ids = set(stall_report.get("blockedCandidateIds") or [])
    blocked_kinds = set(stall_report.get("blockedCandidateKinds") or [])
    blocked_ladder_directions = set(stall_report.get("blockedLadderDirections") or [])
    if candidate_id in blocked_ids:
        return True, f"candidate repeats stalled id {candidate_id}"
    action_name = action_name_for(candidate)
    if kind == "climb_ladder" and action_name in blocked_ladder_directions:
        return True, f"ladder direction {action_name} reverses {stall_report.get('type')}"
    if kind in blocked_kinds:
        return True, f"candidate kind {kind} is blocked by {stall_report.get('type')}"
    return False, None


def score_adjustment(candidate: dict[str, Any], stall_report: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    if stall_report.get("severity") == "none":
        return 0, {}
    blocked, reason = is_candidate_blocked(candidate, stall_report)
    preferred = set(stall_report.get("preferredCandidateKinds") or [])
    kind = candidate.get("kind")
    if blocked:
        return -90, {"stallBlocked": True, "stallBlockReason": reason}
    if kind in preferred:
        return 30, {"stallRecovery": True, "stallRecoveryReason": stall_report.get("recoveryHint")}
    if stall_report.get("severity") == "stalled" and kind == "wait_or_stop":
        return -120, {"stallBlocked": True, "stallBlockReason": "waiting prolongs the detected stall"}
    return 0, {}


def base_report(
    *,
    positions: list[tuple[int, int]],
    candidate_ids: list[str],
    key_codes: list[int],
    gold_counts: list[int],
) -> dict[str, Any]:
    return {
        "stalled": False,
        "severity": "none",
        "type": None,
        "reason": None,
        "phase": None,
        "recentPositions": positions,
        "recentCandidateIds": candidate_ids,
        "recentKeyCodes": key_codes,
        "recentXRange": 0,
        "directionChanges": 0,
        "noRowChange": False,
        "noGoldChange": len(set(gold_counts)) <= 1 if gold_counts else True,
        "sameTileStreak": count_tail_equal(positions),
        "sameCandidateStreak": count_tail_equal(candidate_ids),
        "repeatedCandidateId": candidate_ids[-1] if candidate_ids else None,
        "repeatedCandidateKind": candidate_kind(candidate_ids[-1]) if candidate_ids else None,
        "blockedCandidateId": None,
        "blockedCandidateIds": [],
        "blockedCandidateKinds": [],
        "blockedLadderDirections": [],
        "preferredCandidateKinds": [],
        "oscillationTarget": None,
        "ladderX": None,
        "recentYRange": 0,
        "preferredVerticalDirection": None,
        "recoveryHint": None,
    }


def collect_positions(recent: list[dict[str, Any]]) -> list[tuple[int, int]]:
    positions = []
    for item in recent:
        after = dict_value(item.get("after"))
        runner = dict_value(after.get("runner"))
        x = to_int(runner.get("x"))
        y = to_int(runner.get("y"))
        if x is not None and y is not None:
            positions.append((x, y))
    return positions


def collect_gold_counts(recent: list[dict[str, Any]]) -> list[int]:
    values = []
    for item in recent:
        after = dict_value(item.get("after"))
        gold_count = to_int(after.get("goldCount"))
        if gold_count is not None:
            values.append(gold_count)
    return values


def collect_candidate_ids(recent: list[dict[str, Any]]) -> list[str]:
    return [item["candidateId"] for item in recent if isinstance(item.get("candidateId"), str)]


def collect_key_codes(recent: list[dict[str, Any]]) -> list[int]:
    values = []
    for item in recent:
        key_code = to_int(item.get("keyCode"))
        if key_code is not None:
            values.append(key_code)
    return values


def blocked_candidates_for(
    stall_type: str | None, repeated_candidate_id: str | None, repeated_kind: str | None
) -> tuple[list[str], list[str]]:
    ids = [repeated_candidate_id] if repeated_candidate_id else []
    kinds: list[str] = []
    if stall_type == "horizontal_oscillation":
        kinds.extend(["godmode_progress", "retreat_from_guard", "wait_or_stop"])
    elif stall_type == "same_candidate_no_progress" and repeated_kind:
        kinds.append(repeated_kind)
    elif stall_type == "same_tile_no_progress":
        pass
    elif stall_type == "route_access_loop":
        kinds.append("route_access_dig")
    elif stall_type == "exit_ladder_loop":
        kinds.extend(["godmode_progress", "wait_or_stop"])
    elif stall_type == "wait_loop":
        kinds.append("wait_or_stop")
    return ids, sorted(set(kinds))


def blocked_ladder_directions_for(
    stall_type: str | None, vertical_ladder_loop: dict[str, Any]
) -> list[str]:
    if stall_type != "vertical_ladder_oscillation":
        return []
    if vertical_ladder_loop.get("exitDirection"):
        return ["down", "up"]
    preferred = vertical_ladder_loop.get("preferredVerticalDirection")
    if preferred == "up":
        return ["down"]
    if preferred == "down":
        return ["up"]
    return []


def preferred_recovery_kinds(
    stall_type: str | None,
    gold_complete: bool,
    route_access: dict[str, Any],
    ladder: dict[str, Any],
) -> list[str]:
    if stall_type is None:
        return []
    if gold_complete:
        return ["exit_ladder_route", "climb_ladder", "align_ladder"]
    if stall_type == "vertical_ladder_oscillation":
        if ladder.get("onLadder"):
            return ["godmode_progress", "align_ladder", "collect_same_row_gold", "climb_ladder"]
        return ["climb_ladder", "collect_same_row_gold", "align_ladder", "godmode_progress"]
    if route_access.get("followAvailable"):
        return ["route_access_follow", "continue_fall", "descend_route", "climb_ladder"]
    if route_access.get("available"):
        return ["route_access_dig", "route_access_follow", "continue_fall", "descend_route"]
    if stall_type == "same_tile_no_progress":
        return ["route_access_dig", "route_access_follow", "align_ladder", "godmode_progress", "climb_ladder"]
    if ladder.get("onLadder"):
        return ["climb_ladder", "descend_route", "collect_same_row_gold"]
    return [
        "collect_same_row_gold",
        "climb_ladder",
        "align_ladder",
        "route_access_follow",
        "descend_route",
        "continue_fall",
    ]


def recovery_hint(
    stall_type: str | None, preferred_kinds: list[str], target: dict[str, Any] | None
) -> str | None:
    if stall_type is None:
        return None
    target_text = ""
    if target:
        target_text = f" target={target.get('kind')}({target.get('x')},{target.get('y')})"
    if preferred_kinds:
        return f"{stall_type}: avoid repeated loop; prefer {', '.join(preferred_kinds[:3])}.{target_text}"
    return f"{stall_type}: choose a different candidate that changes row, route, or gold state.{target_text}"


def human_reason(stall_type: str | None) -> str | None:
    if stall_type == "horizontal_oscillation":
        return "bounded horizontal oscillation without row or gold progress"
    if stall_type == "same_candidate_no_progress":
        return "same candidate repeated without row or gold progress"
    if stall_type == "same_tile_no_progress":
        return "runner stayed on the same tile without row or gold progress"
    if stall_type == "route_access_loop":
        return "route-access dig repeated without descent or route follow-through"
    if stall_type == "exit_ladder_loop":
        return "exit phase is looping without climbing or reaching the exit ladder"
    if stall_type == "wait_loop":
        return "stop/wait repeated without progress"
    if stall_type == "vertical_ladder_oscillation":
        return "up/down ladder oscillation without gold progress"
    return None


def detect_vertical_ladder_loop(
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
    vertical_keys = [key for key in key_codes if key in {UP_KEYCODE, DOWN_KEYCODE}]
    if len(x_values) != 1 or len(set(y_values)) not in {2, 3} or len(vertical_keys) < 6:
        return {"detected": False}
    alternating_vertical = all(
        vertical_keys[index] != vertical_keys[index - 1] for index in range(1, len(vertical_keys))
    )
    ladder_candidate_loop = candidate_ids and all(
        candidate_kind(candidate_id) == "climb_ladder" for candidate_id in candidate_ids[-6:]
    )
    if not alternating_vertical or not ladder_candidate_loop:
        return {"detected": False}
    preferred = preferred_vertical_direction(primary_target, current_y=positions[-1][1])
    exit_direction = horizontal_exit_direction(primary_target, movement)
    return {
        "detected": True,
        "ladderX": next(iter(x_values)),
        "recentYRange": max(y_values) - min(y_values),
        "preferredVerticalDirection": preferred,
        "exitDirection": exit_direction,
    }


def preferred_vertical_direction(primary_target: dict[str, Any], current_y: int) -> str | None:
    target_y = to_int(primary_target.get("y"))
    if target_y is None:
        return None
    if target_y < current_y:
        return "up"
    if target_y > current_y:
        return "down"
    return None


def horizontal_exit_direction(primary_target: dict[str, Any], movement: dict[str, Any]) -> str | None:
    direction = primary_target.get("direction")
    if direction == "left" and movement.get("canMoveLeft"):
        return "left"
    if direction == "right" and movement.get("canMoveRight"):
        return "right"
    return None


def action_name_for(candidate: dict[str, Any]) -> str | None:
    action = dict_value(candidate.get("firstAction"))
    key_code = to_int(action.get("keyCode"))
    if key_code == UP_KEYCODE:
        return "up"
    if key_code == DOWN_KEYCODE:
        return "down"
    if key_code == LEFT_KEYCODE:
        return "left"
    if key_code == RIGHT_KEYCODE:
        return "right"
    if key_code == STOP_KEYCODE:
        return "stop"
    if key_code == DIG_LEFT_KEYCODE:
        return "dig_left"
    if key_code == DIG_RIGHT_KEYCODE:
        return "dig_right"
    return None


def find_oscillation_target(
    analysis: dict[str, Any], positions: list[tuple[int, int]]
) -> dict[str, Any] | None:
    xs = [x for x, _y in positions]
    ys = [y for _x, y in positions]
    row = ys[-1]
    min_x = min(xs)
    max_x = max(xs)
    for ladder in analysis.get("rowLadders") or []:
        ladder_x = to_int(ladder.get("x"))
        ladder_y = to_int(ladder.get("y"))
        if ladder_x is None or ladder_y != row:
            continue
        if min_x <= ladder_x <= max_x:
            return {"x": ladder_x, "y": ladder_y, "kind": "ladder"}
    for gold in analysis.get("nearestGold") or []:
        gold_x = to_int(gold.get("x"))
        gold_y = to_int(gold.get("y"))
        if gold_x is None or gold_y != row:
            continue
        if min_x <= gold_x <= max_x:
            return {"x": gold_x, "y": gold_y, "kind": "gold"}
    return None


def candidate_kind(candidate_id: str | None) -> str | None:
    if not candidate_id:
        return None
    known_kinds = [
        "collect_same_row_gold",
        "route_access_follow",
        "route_access_dig",
        "retreat_from_guard",
        "exit_ladder_route",
        "godmode_progress",
        "continue_fall",
        "defensive_dig",
        "climb_ladder",
        "align_ladder",
        "descend_route",
        "wait_or_stop",
    ]
    for kind in known_kinds:
        if candidate_id == kind or candidate_id.startswith(f"{kind}_"):
            return kind
    return candidate_id.rsplit("_", 1)[0]


def count_direction_changes(key_codes: list[int]) -> int:
    horizontal = [key for key in key_codes if key in {LEFT_KEYCODE, RIGHT_KEYCODE}]
    return sum(1 for index in range(1, len(horizontal)) if horizontal[index] != horizontal[index - 1])


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
