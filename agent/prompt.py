from __future__ import annotations

import json

from .config import PUZZLE_RULES_PATH


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


def read_puzzle_rules() -> str:
    try:
        return PUZZLE_RULES_PATH.read_text(encoding="utf-8")[:6000]
    except FileNotFoundError:
        return "Collect all gold, avoid guards, use ladders and ropes, and dig traps to solve the level."


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


def format_recent_actions(history: list[dict]) -> str:
    recent = history[-12:]
    if not recent:
        return "Recent actions:\n- none"

    lines = ["Recent actions:"]
    for item in recent:
        lines.append(
            "- "
            f"tick={item.get('tick')} keyCode={item.get('keyCode')} ticks={item.get('ticks')} "
            f"state={item.get('state')} reason={json.dumps(item.get('reason', ''))}"
        )
    return "\n".join(lines)


def format_snapshot(snapshot: dict) -> str:
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
        format_grid("Current live actor grid (`grid`):", snapshot.get("grid") or []),
        "",
        format_grid("Underlying terrain grid (`baseGrid`):", snapshot.get("baseGrid") or []),
    ]
    return "\n".join(meta)


def build_agent_prompt(snapshot: dict, history: list[dict]) -> str:
    return "\n\n".join(
        [
            "You are choosing the next short Lode Runner input burst for Classic level 1.",
            "You may call helper tools before answering, but your final answer must be JSON only.",
            "Return exactly one next action burst. Choose one allowed keycode and a tick count from 1 to 20.",
            "Allowed keycodes: stop=32, left=37, right=39, up=38, down=40, dig_left=90, dig_right=88.",
            'Return this JSON shape: {"keyCode": 39, "ticks": 4, "reason": "brief explanation"}.',
            "Prefer short, safe bursts that avoid guards, reduce loops, and preserve puzzle progress.",
            "Game rules:\n" + read_puzzle_rules(),
            "Current live snapshot:\n" + format_snapshot(snapshot),
            format_recent_actions(history),
        ]
    )
