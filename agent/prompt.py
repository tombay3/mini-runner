from __future__ import annotations

import json

from .config import AGENT_RULES_PATH
from .reasoning_tools import (
    assess_safe_progress_options,
    detect_progress_stall,
    find_nearest_gold_candidates,
    find_row_ladders,
)


TILE_LEGEND = [
    (" ", "empty space"),
    ("#", "diggable brick; valid dig target when it is down-left or down-right"),
    ("@", "solid indestructible block; never dig or pass through"),
    ("H", "ladder"),
    ("-", "rope / bar"),
    ("X", "trap / dug hole"),
    ("?", "unknown / missing cell"),
]


def read_agent_rules() -> str:
    try:
        return AGENT_RULES_PATH.read_text(encoding="utf-8")[:6000]
    except FileNotFoundError:
        return (
            "Classic level 1 focus: collect all gold, avoid immediate guard contact, "
            "prefer nearby same-row gold and visible ladders, and avoid repeated retreat loops."
        )


def format_tile_legend() -> str:
    return "\n".join(f"- `{char}` = {meaning}" for char, meaning in TILE_LEGEND)


def get_dimensions(snapshot: dict) -> tuple[int, int]:
    dimensions = snapshot.get("dimensions") or {}
    width = dimensions.get("width") or 28
    height = dimensions.get("height") or 16
    return int(width), int(height)


def get_terrain_grid(snapshot: dict) -> list[str]:
    terrain_grid = snapshot.get("terrainGrid")
    if isinstance(terrain_grid, list) and terrain_grid:
        return [row if isinstance(row, str) else str(row) for row in terrain_grid]
    return []


def format_grid(title: str, rows: list[str]) -> str:
    if not rows:
        return f"{title}\n(no rows available)"
    width = max(len(row) for row in rows)
    columns = " ".join(str(index).rjust(2) for index in range(width))
    body = [
        f"y={str(index).rjust(2)} | " + " ".join(format_grid_cell(row, column) for column in range(width))
        for index, row in enumerate(rows)
    ]
    return "\n".join([title, f"      x: {columns}", *body])


def format_grid_cell(row: str, column: int) -> str:
    char = row[column] if column < len(row) else "?"
    return "." if char == " " else char


def format_structure_positions(
    title: str,
    rows: list[str],
    targets: set[str],
    label: str,
    usage: str,
) -> str:
    positions = []
    for y, row in enumerate(rows):
        for x, char in enumerate(row):
            if char in targets:
                positions.append(f"({x},{y})")
    if not positions:
        return f"{title}: {label}=none. {usage}"
    return f"{title}: {label}=" + ", ".join(positions) + f". {usage}"


def to_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def terrain_cell(rows: list[str], x: int, y: int) -> str:
    if y < 0 or y >= len(rows):
        return "out-of-bounds"
    row = rows[y]
    if x < 0 or x >= len(row):
        return "out-of-bounds"
    return format_grid_cell(row, x)


def format_dig_validation(snapshot: dict, rows: list[str]) -> str:
    runner = snapshot.get("runner") or {}
    runner_x = to_int(runner.get("x"))
    runner_y = to_int(runner.get("y"))
    if runner_x is None or runner_y is None:
        return (
            "terrainGrid validation: digging unavailable because runner coordinates are missing. "
            "Remember: only `#` is diggable; `@` is solid and non-diggable."
        )

    checks = [
        ("dig_left", runner_x - 1, runner_y, runner_x - 1, runner_y + 1),
        ("dig_right", runner_x + 1, runner_y, runner_x + 1, runner_y + 1),
    ]
    lines = [
        "terrainGrid validation: digging",
        "- Only `#` is diggable brick. `@` is solid indestructible terrain and is never a dig target.",
        (
            "- A dig action needs an open adjacent side cell and a `#` target cell "
            "down-left or down-right from the runner."
        ),
    ]
    for action, side_x, side_y, target_x, target_y in checks:
        side_tile = terrain_cell(rows, side_x, side_y)
        target_tile = terrain_cell(rows, target_x, target_y)
        possible = side_tile == "." and target_tile == "#"
        lines.append(
            "- "
            f"{action}: side ({side_x},{side_y})={side_tile}, "
            f"target ({target_x},{target_y})={target_tile}, "
            f"possible={'yes' if possible else 'no'}"
        )
    return "\n".join(lines)


def format_board_guide(snapshot: dict) -> str:
    width, height = get_dimensions(snapshot)
    return "\n".join(
        [
            "Board format:",
            f"- Classic level 1 is a fixed {width} x {height} ASCII grid.",
            "- Coordinates use (x,y), with (0,0) at the top-left.",
            "- `terrainGrid` is structural terrain only. It does not contain gold, runner, or guards.",
            "- In terrainGrid rows, `.` means empty space. Other symbols are structural tiles at the x-column shown above.",
            "- Runner, guards, and gold are listed separately as coordinates.",
            "- Read terrain in physical movement terms: ladders support vertical climb up/down; ropes support horizontal crossing while open air and falling may exist below them.",
            "- The ladder and rope coordinate lists are authoritative validation aids. If your visual read of the 2D grid disagrees with those lists, trust the coordinate lists.",
            "- Critical tile distinction: `#` is diggable brick; `@` is solid and non-diggable. Do not plan to dig `@`.",
            "- Offsets are in-tile movement: (0,0) means centered; nonzero offsets matter near guards, gold, ladders, ropes, and falls.",
        ]
    )


def format_exit_instruction(snapshot: dict) -> str:
    gold = snapshot.get("gold") or {}
    gold_complete = bool(gold.get("complete", snapshot.get("goldComplete")))
    if not gold_complete:
        return ""
    return "\n".join(
        [
            "Exit instruction:",
            "- All gold is collected.",
            "- The previously hidden exit ladder is now visible as `H` in `terrainGrid`.",
            "- Validate its coordinates against the ladder list, then climb the visible exit ladder route to row 0.",
        ]
    )


def format_offset_summary(entity: dict) -> str:
    summary = entity.get("summary") or {}
    centered = summary.get("centered")
    direction = summary.get("offsetDirection")
    if centered is None and direction is None:
        return f"offset=({entity.get('xOffset')},{entity.get('yOffset')})"
    centered_label = "yes" if centered else "no"
    return (
        f"offset=({entity.get('xOffset')},{entity.get('yOffset')}) "
        f"centered={centered_label} offsetDirection={direction}"
    )


def format_runner(snapshot: dict) -> str:
    runner = snapshot.get("runner") or {}
    if not runner:
        return "Runner: unavailable"
    return "\n".join(
        [
            "Runner:",
            (
                "- "
                f"position=({runner.get('x')},{runner.get('y')}) "
                f"action={runner.get('actionName')} "
                f"{format_offset_summary(runner)} "
                f"lastLeftRight={runner.get('lastLeftRight')}"
            ),
        ]
    )


def format_guards(snapshot: dict) -> str:
    guards = snapshot.get("guards") or []
    if not guards:
        return "Guards:\n- none visible"

    lines = ["Guards:"]
    for guard in guards:
        lines.append(
            "- "
            f"id={guard.get('id')} position=({guard.get('x')},{guard.get('y')}) "
            f"sameRowAsRunner={'yes' if guard.get('sameRowAsRunner') else 'no'} "
            f"action={guard.get('actionName')} hasGold={guard.get('hasGold')} "
            f"{format_offset_summary(guard)}"
        )
    return "\n".join(lines)


def format_gold(snapshot: dict) -> str:
    gold = snapshot.get("gold") or {}
    visible_positions = gold.get("visiblePositions")
    if not isinstance(visible_positions, list):
        visible_positions = []
    carried_by_guards = gold.get("carriedByGuards")
    if not isinstance(carried_by_guards, list):
        carried_by_guards = [
            guard
            for guard in snapshot.get("guards") or []
            if isinstance(guard, dict) and (guard.get("hasGold") or 0) > 0
        ]

    lines = [
        "Gold:",
        (
            "- "
            f"remainingCount={gold.get('remainingCount', snapshot.get('goldCount'))} "
            f"complete={gold.get('complete', snapshot.get('goldComplete'))}"
        ),
    ]
    if visible_positions:
        positions = ", ".join(f"({item.get('x')},{item.get('y')})" for item in visible_positions)
        lines.append(f"- visiblePositions={positions}")
    else:
        lines.append("- visiblePositions=none")

    if carried_by_guards:
        carried = ", ".join(
            f"guard {item.get('id')} at ({item.get('x')},{item.get('y')}) hasGold={item.get('hasGold')}"
            for item in carried_by_guards
        )
        lines.append(f"- carriedByGuards={carried}")
    else:
        lines.append("- carriedByGuards=none")
    return "\n".join(lines)


def format_timing(snapshot: dict) -> str:
    timing = snapshot.get("timing") or {}
    return "\n".join(
        [
            "Timing:",
            (
                "- "
                f"recordTick={timing.get('recordTick', snapshot.get('tick'))} "
                f"gameTime={timing.get('gameTime', snapshot.get('time'))} "
                f"playTickTimer={timing.get('playTickTimer', snapshot.get('playTickTimer'))}"
            ),
            (
                "- "
                f"ticksPerSecond={timing.get('ticksPerSecond', 16)} "
                f"secondPhase={timing.get('secondPhase', '')}"
            ),
        ]
    )


def format_recent_actions(snapshot: dict, history: list[dict]) -> str:
    recent = history[-4:]
    if not recent:
        return "Recent behavior:\n- none"

    stall = detect_progress_stall(snapshot, history, window=8)
    keycode_names = {
        32: "stop",
        37: "left",
        38: "up",
        39: "right",
        40: "down",
        88: "dig_right",
        90: "dig_left",
    }

    lines = [
        "Recent behavior:",
        f"- stallDetected={'yes' if stall.get('stalled') else 'no'}",
        f"- rowChangeLikelyRecent={'yes' if stall.get('rowChangeLikelyRecent') else 'no'}",
    ]
    if stall.get("dominantDirection"):
        lines.append(
            "- "
            f"recentDominantDirection={stall.get('dominantDirection')} "
            f"count={stall.get('dominantCount')}"
        )
    if stall.get("oscillating"):
        lines.append("- oscillating=yes")
    if stall.get("edgePressure"):
        lines.append(f"- edgePressure=yes toward {stall.get('edgeDirection')}")

    lines.append("- lastActions:")
    for item in recent:
        key_code = item.get("keyCode", 32)
        lines.append(
            "  "
            f"tick={item.get('tick')} action={keycode_names.get(key_code, key_code)} "
            f"ticks={item.get('ticks')} state={item.get('state')}"
        )
    return "\n".join(lines)


def format_progress_annotations(snapshot: dict, history: list[dict]) -> str:
    runner = snapshot.get("runner") or {}
    runner_y = runner.get("y")
    gold_candidates = find_nearest_gold_candidates(snapshot, limit=4)
    row_ladders = [
        item for item in find_row_ladders(snapshot, limit=4) if item.get("visible")
    ]
    stall = detect_progress_stall(snapshot, history, window=8)
    progress = assess_safe_progress_options(snapshot, history, limit=4)

    lines = [
        "Progress annotations:",
        f"- runnerRow={runner_y} (same row as the runner)",
        f"- rowChangeLikelyRecent={'yes' if stall.get('rowChangeLikelyRecent') else 'no'}",
        f"- stallDetected={'yes' if stall.get('stalled') else 'no'}",
    ]
    if stall.get("dominantDirection"):
        lines.append(
            "- "
            f"recentDominantRetreat={stall.get('dominantDirection')} "
            f"count={stall.get('dominantCount')}"
        )
    if stall.get("edgePressure"):
        lines.append(f"- edgePressure=yes toward {stall.get('edgeDirection')}")

    if gold_candidates:
        lines.append("- nearestGoldCandidates:")
        for gold in gold_candidates:
            lines.append(
                "  "
                f"({gold['x']},{gold['y']}) distance={gold['distance']} "
                f"sameRow={'yes' if gold['sameRow'] else 'no'} direction={gold['direction']}"
            )
    else:
        lines.append("- nearestGoldCandidates: none visible")

    if row_ladders:
        lines.append("- visibleLaddersOnRunnerRow:")
        for ladder in row_ladders:
            lines.append(
                "  "
                f"({ladder['x']},{ladder['y']}) distance={ladder['distance']} "
                f"direction={ladder['direction']}"
            )
    else:
        lines.append("- visibleLaddersOnRunnerRow: none")

    if progress.get("options"):
        lines.append("- safeProgressOptions:")
        for option in progress["options"]:
            lines.append(f"  {option.get('detail')}")

    return "\n".join(lines)


def format_snapshot(snapshot: dict, history: list[dict] | None = None) -> str:
    terrain_grid = get_terrain_grid(snapshot)
    exit_instruction = format_exit_instruction(snapshot)
    meta = [
        format_board_guide(snapshot),
        "",
        "Terrain tile legend:",
        format_tile_legend(),
        "",
        exit_instruction if exit_instruction else None,
        "" if exit_instruction else None,
        "Game state:",
        (
            f"- playData={snapshot.get('playData')} level={snapshot.get('level')} "
            f"playMode={snapshot.get('playMode')} gameState={snapshot.get('gameStateName')}"
        ),
        f"- lastFailureReason={json.dumps(snapshot.get('lastFailureReason', ''))}",
        "",
        format_timing(snapshot),
        "",
        format_runner(snapshot),
        "",
        format_guards(snapshot),
        "",
        format_gold(snapshot),
        "",
        format_progress_annotations(snapshot, history or []),
        "",
        format_grid("terrainGrid (structural tiles only, dot = empty):", terrain_grid),
        "",
        "Use coordinate lists below to validate any coordinates you read from the 2D terrainGrid before planning movement:",
        "",
        format_structure_positions(
            "terrainGrid validation",
            terrain_grid,
            {"H"},
            "ladders",
            "Use these as the authoritative climbable vertical coordinates for moving up or down.",
        ),
        "",
        format_structure_positions(
            "terrainGrid validation",
            terrain_grid,
            {"-"},
            "ropes",
            "Use these as the authoritative horizontal crossing coordinates. Free falling may be possible from rope positions if there is no support below.",
        ),
        "",
        format_dig_validation(snapshot, terrain_grid),
    ]
    return "\n".join(item for item in meta if item is not None)


def build_agent_prompt(
    snapshot: dict, history: list[dict], retry_note: str | None = None
) -> str:
    sections = [
        "You are choosing the next short Lode Runner input burst for Classic level 1.",
        "You may call helper tools before answering, but your final answer must be JSON only.",
        "Return exactly one next action burst. Choose one allowed keycode and a tick count from 1 to 20.",
        "Allowed keycodes: stop=32, left=37, right=39, up=38, down=40, dig_left=90, dig_right=88.",
        'Return this JSON shape: {"keyCode": 39, "ticks": 4, "reason": "brief explanation"}.',
        "Agent rules:\n" + read_agent_rules(),
        "Current live snapshot:\n" + format_snapshot(snapshot, history),
        format_recent_actions(snapshot, history),
    ]
    if retry_note:
        sections.append("Retry instruction:\n" + retry_note)
    return "\n\n".join(sections)
