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
    ("#", "brick / diggable block"),
    ("@", "solid / indestructible block"),
    ("H", "ladder"),
    ("-", "rope / bar"),
    ("X", "trap / dug hole"),
    ("S", "hidden ladder"),
    ("$", "gold"),
    ("0", "guard enemy (digit zero, not the letter O)"),
    ("&", "runner / player"),
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


def format_grid(title: str, rows: list[str]) -> str:
    if not rows:
        return f"{title}\n(no rows available)"
    width = max(len(row) for row in rows)
    header = "    " + "".join(str(i % 10) for i in range(width))
    body = [f"{str(index).rjust(2)}: {row}" for index, row in enumerate(rows)]
    return "\n".join([title, header, *body])


def format_runner(snapshot: dict) -> str:
    runner = snapshot.get("runner") or {}
    if not runner:
        return "Runner: unavailable"
    return (
        "Runner: "
        f"x={runner.get('x')} y={runner.get('y')} "
        f"action={runner.get('actionName')} "
        f"xOffset={runner.get('xOffset')} yOffset={runner.get('yOffset')} "
        f"lastLeftRight={runner.get('lastLeftRight')}"
    )


def format_guards(snapshot: dict) -> str:
    guards = snapshot.get("guards") or []
    if not guards:
        return "Guards:\n- none visible"

    lines = ["Guards:"]
    for guard in guards:
        lines.append(
            "- "
            f"id={guard.get('id')} x={guard.get('x')} y={guard.get('y')} "
            f"action={guard.get('actionName')} hasGold={guard.get('hasGold')} "
            f"xOffset={guard.get('xOffset')} yOffset={guard.get('yOffset')}"
        )
    return "\n".join(lines)


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
    meta = [
        "Snapshot guide:",
        "- `grid` is the live board with dynamic actors overlaid.",
        "- `baseGrid` is the underlying terrain layout and is easier for route planning.",
        "- Distinguish carefully: `$` is gold, `0` is a guard, and `&` is the runner.",
        "- Row 0 is the top of the level. Column 0 is the left side.",
        "",
        "Tile legend:",
        format_tile_legend(),
        "",
        "Game state:",
        (
            f"- playData={snapshot.get('playData')} level={snapshot.get('level')} "
            f"playMode={snapshot.get('playMode')} gameState={snapshot.get('gameStateName')}"
        ),
        (
            f"- tick={snapshot.get('tick')} time={snapshot.get('time')} "
            f"playTickTimer={snapshot.get('playTickTimer')}"
        ),
        (
            f"- goldCount={snapshot.get('goldCount')} goldComplete={snapshot.get('goldComplete')} "
            f"lastFailureReason={json.dumps(snapshot.get('lastFailureReason', ''))}"
        ),
        "",
        format_runner(snapshot),
        "",
        format_guards(snapshot),
        "",
        format_progress_annotations(snapshot, history or []),
        "",
        format_grid("Current live actor grid (`grid`):", snapshot.get("grid") or []),
        "",
        format_grid(
            "Underlying terrain grid (`baseGrid`):", snapshot.get("baseGrid") or []
        ),
    ]
    return "\n".join(meta)


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
