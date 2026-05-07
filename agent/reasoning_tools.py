from __future__ import annotations

from collections import Counter
from typing import Any


def build_reasoning_tools(snapshot: dict[str, Any], history: list[dict[str, Any]]) -> list:
    runner = snapshot.get("runner") or {}
    guards = snapshot.get("guards") or []
    grid = snapshot.get("grid") or []

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

    def assess_guard_risk() -> dict[str, Any]:
        """Assess whether nearby guards create immediate danger and which direction seems safer."""

        runner_x = runner.get("x")
        runner_y = runner.get("y")
        if runner_x is None or runner_y is None:
            return {"risk": "unknown", "nearestGuardDistance": None}

        distances = []
        same_row = []
        for guard in guards:
            guard_x = guard.get("x")
            guard_y = guard.get("y")
            if guard_x is None or guard_y is None:
                continue
            distance = abs(int(guard_x) - int(runner_x)) + abs(int(guard_y) - int(runner_y))
            distances.append(distance)
            if int(guard_y) == int(runner_y):
                same_row.append({"x": guard_x, "distance": abs(int(guard_x) - int(runner_x))})

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
            "sameRowGuards": same_row[:4],
        }

    def suggest_subgoal() -> dict[str, Any]:
        """Suggest a short-term puzzle objective for the next action burst."""

        if snapshot.get("goldComplete"):
            objective = "reach_exit_ladder"
            detail = "All gold is collected. Move toward the revealed exit path."
        elif (snapshot.get("goldCount") or 0) <= 2:
            objective = "secure_last_gold"
            detail = "Only a small amount of gold remains. Favor safe pickup routes."
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
        assess_guard_risk,
        suggest_subgoal,
        evaluate_last_action,
    ]
