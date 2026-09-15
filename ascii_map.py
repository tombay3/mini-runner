"""Compact, dependency-free ASCII rendering for a trace state snapshot."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from math import isfinite
from textwrap import wrap
from typing import Any

BOARD = {"min_x": 0, "max_x": 27, "min_y": 0, "max_y": 15}


def _coordinate(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, Mapping):
        return None
    try:
        x = float(value["x"])
        y = float(value["y"])
    except (KeyError, OverflowError, TypeError, ValueError):
        return None
    if not isfinite(x) or not isfinite(y):
        return None
    return round(x), round(y)


def _point_text(point: tuple[int, int] | None) -> str:
    return f"({point[0]},{point[1]})" if point else "not recorded"


def normalize_tile(tile: Any) -> str:
    normalized = str(tile or "").strip().lower()
    if normalized in {"$", "gold"}:
        return "GOLD"
    if normalized in {"h", "ladder"}:
        return "LADDER"
    return normalized.upper() if normalized else "ROUTE"


def _target(value: Any) -> dict[str, Any] | None:
    point = _coordinate(value)
    if point is None:
        return None
    return {
        "point": point,
        "tile": normalize_tile(value.get("tile"))
        if isinstance(value, Mapping)
        else "ROUTE",
    }


def _same_point(first: tuple[int, int] | None, second: tuple[int, int] | None) -> bool:
    return bool(first and second and first == second)


def _same_guard(
    first: Mapping[str, Any] | None, second: Mapping[str, Any] | None
) -> bool:
    if not first or not second:
        return False
    if first.get("id") is not None and second.get("id") is not None:
        return str(first.get("id")) == str(second.get("id"))
    return _same_point(_coordinate(first), _coordinate(second))


def _in_board(point: tuple[int, int] | None) -> bool:
    return bool(
        point
        and BOARD["min_x"] <= point[0] <= BOARD["max_x"]
        and BOARD["min_y"] <= point[1] <= BOARD["max_y"]
    )


def _outside_suffix(point: tuple[int, int] | None) -> str:
    return "" if _in_board(point) else " [outside board]"


def _guard_observations(state: Mapping[str, Any]) -> list[dict[str, Any]]:
    risk = state.get("guardRisk") or {}
    nearby = risk.get("nearbyGuards") if isinstance(risk, Mapping) else None
    guards = (
        nearby if isinstance(nearby, list) and nearby else state.get("guards") or []
    )
    result = [
        guard for guard in guards if isinstance(guard, Mapping) and _coordinate(guard)
    ]

    pressure = risk.get("pressureGuard") if isinstance(risk, Mapping) else None
    if (
        isinstance(pressure, Mapping)
        and _coordinate(pressure)
        and not any(_same_guard(guard, pressure) for guard in result)
    ):
        result.append(dict(pressure))
    return [dict(guard) for guard in result]


def _carries_gold(value: Any) -> bool:
    try:
        return float(value or 0) > 0
    except (OverflowError, TypeError, ValueError):
        return False


def _visible_gold(state: Mapping[str, Any]) -> list[Any]:
    gold = state.get("gold")
    if not isinstance(gold, Mapping):
        return []
    positions = gold.get("visiblePositions")
    return positions if isinstance(positions, list) else []


def _line_points(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    """Return integer cells between two points using a lightweight Bresenham line."""
    x0, y0 = start
    x1, y1 = end
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    error = dx + dy
    points = []

    while True:
        points.append((x0, y0))
        if x0 == x1 and y0 == y1:
            break
        twice_error = 2 * error
        if twice_error >= dy:
            error += dy
            x0 += sx
        if twice_error <= dx:
            error += dx
            y0 += sy
    return points


def has_coordinate_geometry(state: Any) -> bool:
    if not isinstance(state, Mapping):
        return False
    if _coordinate(state.get("runner")) or _target(state.get("primaryProgressTarget")):
        return True
    if _guard_observations(state):
        return True
    return any(
        _coordinate(point)
        for point in _visible_gold(state)
        if isinstance(point, Mapping)
    )


def find_selected_candidate(
    candidates: Any, selected_id: Any
) -> Mapping[str, Any] | None:
    if not isinstance(candidates, list):
        return None
    normalized_id = str(selected_id or "")
    return next(
        (
            candidate
            for candidate in candidates
            if isinstance(candidate, Mapping)
            and str(candidate.get("id") or "") == normalized_id
        ),
        None,
    )


def render_ascii_map(
    state: Any,
    selected_candidate: Mapping[str, Any] | None = None,
) -> str:
    """Render a selected-step state as a compact, fixed-width coordinate map."""
    if not isinstance(state, Mapping) or not has_coordinate_geometry(state):
        return "NO COORDINATE GEOMETRY RECORDED"

    runner = _coordinate(state.get("runner"))
    target = _target(state.get("primaryProgressTarget"))
    candidate_target = _target(
        selected_candidate.get("target")
        if isinstance(selected_candidate, Mapping)
        else None
    )
    waypoint = (
        candidate_target
        if candidate_target
        and not _same_point(
            candidate_target["point"], target["point"] if target else None
        )
        else None
    )

    guards = _guard_observations(state)
    risk = state.get("guardRisk") or {}
    pressure = risk.get("pressureGuard") if isinstance(risk, Mapping) else None
    pressure = (
        pressure if isinstance(pressure, Mapping) and _coordinate(pressure) else None
    )
    visible_gold = _visible_gold(state)
    gold_points = [
        point
        for point in (
            _coordinate(value) for value in visible_gold if isinstance(value, Mapping)
        )
        if point and not _same_point(point, target["point"] if target else None)
    ]

    min_x = BOARD["min_x"]
    max_x = BOARD["max_x"]
    min_y = BOARD["min_y"]
    max_y = BOARD["max_y"]

    occupants: dict[tuple[int, int], list[str]] = defaultdict(list)
    annotations: list[str] = []

    if runner:
        if _in_board(runner):
            occupants[runner].append("R")
        annotations.append(f"RUNNER {_point_text(runner)}{_outside_suffix(runner)}")
    if target:
        if _in_board(target["point"]):
            occupants[target["point"]].append("T")
        annotations.append(
            f"TARGET: {target['tile']} {_point_text(target['point'])}"
            f"{_outside_suffix(target['point'])}"
        )
    if waypoint:
        if _in_board(waypoint["point"]):
            occupants[waypoint["point"]].append("W")
        annotations.append(
            f"WAYPOINT: {waypoint['tile']} {_point_text(waypoint['point'])}"
            f"{_outside_suffix(waypoint['point'])}"
        )

    for point in gold_points:
        if _in_board(point):
            occupants[point].append("$")
    if gold_points:
        annotations.append(
            "VISIBLE GOLD: "
            + ", ".join(
                f"{_point_text(point)}{_outside_suffix(point)}" for point in gold_points
            )
        )

    state_risk = (
        str(risk.get("risk") or "unavailable").upper()
        if isinstance(risk, Mapping)
        else "UNAVAILABLE"
    )
    for index, guard in enumerate(guards):
        point = _coordinate(guard)
        if not point:
            continue
        is_pressure = _same_guard(guard, pressure)
        carrying = _carries_gold(guard.get("hasGold"))
        marker = "P" if is_pressure else "C" if carrying else "G"
        if _in_board(point):
            occupants[point].append(marker)
        guard_id = guard.get("id", index)
        risk_label = str(guard.get("risk") or state_risk).lower()
        details = [
            (
                f"GUARD {guard_id} {_point_text(point)} [{risk_label} risk]"
                f"{_outside_suffix(point)}"
            )
        ]
        if is_pressure:
            details[0] = f"PRESSURE: {details[0]}"
        if carrying:
            details[0] += " carrying gold"
        annotations.append(details[0])

    destination = waypoint or target
    destination_point = destination["point"] if destination else None
    if (
        runner
        and destination_point
        and _in_board(runner)
        and _in_board(destination_point)
        and not _same_point(runner, destination_point)
    ):
        path = _line_points(runner, destination_point)
        annotations.append(
            f"PATH: RUNNER -> {'WAYPOINT' if waypoint else 'TARGET'} {_point_text(destination_point)}"
        )
    else:
        path = []
        if runner and destination_point and not _same_point(runner, destination_point):
            annotations.append(
                f"PATH: RUNNER -> {'WAYPOINT' if waypoint else 'TARGET'} "
                f"{_point_text(destination_point)} [outside board]"
            )

    header = f"ASCII MAP  x={min_x}..{max_x}  y={min_y}..{max_y}  risk={state_risk}"
    axis = "    " + "".join(str(abs(x) % 10) for x in range(min_x, max_x + 1))
    rows = [header, axis, "   +" + "-" * (max_x - min_x + 1)]
    path_cells = set(path[1:-1])
    for y in range(min_y, max_y + 1):
        cells = []
        for x in range(min_x, max_x + 1):
            point = (x, y)
            tokens = occupants.get(point, [])
            if len(set(tokens)) > 1:
                cell = "@"
            elif tokens:
                cell = tokens[0]
            elif point in path_cells:
                cell = "·"
            else:
                cell = " "
            cells.append(cell)
        rows.append(f"{y:>3}|" + "".join(cells))
    rows.append("   +" + "-" * (max_x - min_x + 1))
    rows.append("    " + "".join(str(abs(x) % 10) for x in range(min_x, max_x + 1)))
    rows.append("LEGEND: R runner · T target · W waypoint · $ gold")
    rows.append("        G guard · P pressure · C guard+gold · @ overlap")
    for annotation in annotations:
        rows.extend(wrap(annotation, width=58, subsequent_indent="  ") or [""])
    return "\n".join(rows)
