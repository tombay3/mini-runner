from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import AgentRequestError, validate_agent_request  # noqa: E402
from agent.candidates import (  # noqa: E402
    CandidateBuilder,
    add_emergency_hold_candidate,
    analyze_state,
    choose_ladder_direction,
    generate_candidates,
)
from agent.config import MAX_CANDIDATE_LIMIT  # noqa: E402
from agent.candidates import candidate_lane  # noqa: E402
from agent.loop_tools import (  # noqa: E402
    build_loop_report,
    candidate_kind,
    candidate_suppression_reason,
)
from agent.prompt import build_agent_prompt, read_agent_rules  # noqa: E402
from agent.reasoning_tools import get_movement_affordance  # noqa: E402


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def assert_true(value: Any, message: str) -> None:
    if not value:
        raise AssertionError(message)


def snapshot(*, grid: list[str], runner: dict[str, Any], gold_complete: bool = False) -> dict[str, Any]:
    return {
        "playData": 1,
        "level": 1,
        "gameStateName": "running",
        "godMode": False,
        "runner": runner,
        "guards": [],
        "gold": {
            "complete": gold_complete,
            "remainingCount": 0 if gold_complete else 2,
            "visiblePositions": [] if gold_complete else [{"x": 1, "y": 1}, {"x": 5, "y": 1}],
            "carriedByGuards": [],
        },
        "goldComplete": gold_complete,
        "goldCount": 0 if gold_complete else 2,
        "terrainGrid": grid,
        "grid": grid,
    }


def check_runtime_boundary() -> None:
    valid = {
        "playData": 1,
        "level": 1,
        "snapshot": {"playData": 1, "level": 1},
        "history": [],
    }
    _, _, options = validate_agent_request(valid)
    assert_equal(
        set(options),
        {"model", "modelProfile", "runId"},
        "only durable request options are exposed",
    )
    for invalid in (
        {**valid, "playData": 2},
        {**valid, "level": 2},
    ):
        try:
            validate_agent_request(invalid)
        except AgentRequestError:
            pass
        else:
            raise AssertionError(f"invalid request accepted: {invalid}")


def check_geometry_candidates() -> None:
    grid = ["       ", " H   H ", "#######", "       "]
    state = snapshot(
        grid=grid,
        runner={"x": 3, "y": 1, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
    )
    candidates, _analysis = generate_candidates(state, [])
    assert_true(candidates, "geometry snapshot produces candidates")
    audit = _analysis["candidateAudit"]
    assert_true(audit, "candidate construction records an audit")
    assert_true(
        all(item.get("disposition") != "validated" for item in audit),
        "candidate finalization classifies every validated proposal",
    )
    assert_true(
        all("classic" not in str(candidate).lower() for candidate in candidates),
        "generated candidates contain no map-specific route knowledge",
    )

    emergency_state = snapshot(
        grid=["@@@@", "@  @", "@@@@"],
        runner={"x": 1, "y": 1, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
    )
    emergency_state["guards"] = [
        {"id": 1, "x": 1, "y": 1, "xOffset": 0, "yOffset": 0, "actionName": "left"}
    ]
    emergency_history = [
        {
            "candidateId": "wait_or_stop",
            "keyCode": 32,
            "after": {"runner": {"x": 1, "y": 1}, "goldCount": 2},
        }
        for _ in range(6)
    ]
    emergency_analysis = analyze_state(emergency_state, emergency_history)
    emergency_builder = CandidateBuilder(
        snapshot=emergency_state,
        analysis=emergency_analysis,
        max_action_ticks=20,
        limit=7,
    )
    add_emergency_hold_candidate(emergency_builder.add, emergency_analysis["risk"])
    emergency_candidates, emergency_analysis = emergency_builder.finalize()
    assert_true(emergency_candidates, "looped emergency state retains a candidate")
    assert_true(
        any(candidate["kind"] == "emergency_hold" for candidate in emergency_candidates),
        "looped emergency state retains emergency_hold",
    )
    assert_true(
        any(
            item.get("kind") == "emergency_hold" and item.get("disposition") == "exposed"
            for item in emergency_analysis["candidateAudit"]
        ),
        "emergency_hold is exposed in the final candidate audit",
    )

    exit_grid = ["   S   ", "   S   ", "#######"]
    exit_state = snapshot(
        grid=exit_grid,
        runner={"x": 3, "y": 1, "xOffset": 0, "yOffset": 8, "actionName": "up"},
        gold_complete=True,
    )
    affordance = get_movement_affordance(exit_state)
    assert_true(affordance["canFinishExitClimb"], "exit completion derives from current exit tile")
    exit_candidates, _ = generate_candidates(exit_state, [])
    assert_true(
        any(candidate["kind"] == "exit_ladder_route" for candidate in exit_candidates),
        "revealed exit produces a geometry-driven exit candidate",
    )


def check_target_relative_ladder_direction() -> None:
    upward_target = {
        "goldComplete": False,
        "runner": {"x": 14, "y": 5},
        "primaryProgressTarget": {"x": 4, "y": 6},
    }
    downward_target = {
        "goldComplete": False,
        "runner": {"x": 7, "y": 5},
        "primaryProgressTarget": {"x": 20, "y": 7},
    }
    assert_equal(
        choose_ladder_direction({}, upward_target),
        "down",
        "ladder direction follows the target row instead of coordinates",
    )
    assert_equal(
        choose_ladder_direction({}, downward_target),
        "down",
        "ladder direction remains target-relative when no gold is visible",
    )


def check_loop_recovery() -> None:
    vertical_history = [
        {
            "candidateId": candidate_id,
            "keyCode": key_code,
            "after": {"runner": {"x": 14, "y": y}, "goldCount": 3},
        }
        for candidate_id, key_code, y in (
            ("climb_ladder_14_6_up", 38, 5),
            ("descend_route_18_6_down", 40, 6),
            ("climb_ladder_14_6_up", 38, 5),
            ("descend_route_18_6_down", 40, 6),
            ("climb_ladder_14_6_up", 38, 5),
            ("descend_route_18_6_down", 40, 6),
        )
    ]
    vertical = build_loop_report(
        {"activeDig": {}, "primaryProgressTarget": {}, "movement": {}},
        vertical_history,
    )
    assert_equal(vertical["type"], "vertical_cycle", "alternating ladder loop is detected")
    assert_true(
        candidate_suppression_reason(
            {
                "id": "descend_route_18_6_down",
                "kind": "descend_route",
                "firstAction": {"keyCode": 40},
            },
            vertical,
        )
        is not None,
        "vertical-cycle suppression covers descent routes",
    )

    horizontal_history = [
        {
            "candidateId": candidate_id,
            "keyCode": key_code,
            "before": {"runner": {"x": before_x, "y": 6}},
            "after": {"runner": {"x": after_x, "y": 6}, "goldCount": 2},
        }
        for candidate_id, key_code, before_x, after_x in (
            ("align_ladder_25_6_right", 39, 14, 16),
            ("align_ladder_14_6_left", 37, 16, 14),
            ("align_ladder_25_6_right", 39, 14, 16),
            ("align_ladder_14_6_left", 37, 16, 14),
            ("align_ladder_25_6_right", 39, 14, 16),
            ("align_ladder_14_6_left", 37, 16, 14),
        )
    ]
    horizontal = build_loop_report(
        {"activeDig": {}, "primaryProgressTarget": {}, "movement": {}},
        horizontal_history,
    )
    assert_equal(
        horizontal["type"],
        "horizontal_cycle",
        "target-reaching ladder alignment does not hide horizontal oscillation",
    )
    assert_true(
        candidate_suppression_reason(
            {
                "id": "emergency_hold_guard_loop",
                "kind": "emergency_hold",
                "firstAction": {"keyCode": 32},
            },
            horizontal,
        )
        is None,
        "loop filtering preserves the emergency safety fallback",
    )


def check_no_legacy_knowledge() -> None:
    assert_true(candidate_kind("removed_kind_1_1_left") != "removed_kind", "unknown route kinds do not become supported candidates")
    assert_equal(candidate_lane("collect_same_row_gold"), "progress", "progress lane is shared")
    assert_equal(candidate_lane("unknown_kind"), "fallback", "unknown kinds use fallback lane")
    rules = read_agent_rules()
    prompt = build_agent_prompt({}, candidates=[], analysis={})
    assert_true("classic level" not in rules.lower(), "rules contain no level-specific guidance")
    assert_true("classic level" not in prompt.lower(), "prompt contains no level-specific guidance")
    source_files = [
        ROOT / "agent" / "candidates.py",
        ROOT / "agent" / "loop_tools.py",
        ROOT / "agent" / "reasoning_tools.py",
    ]
    for path in source_files:
        source = path.read_text(encoding="utf-8").lower()
        assert_true("fixed route table" not in source, f"{path.name} has no fixed route table")
    candidate_source = (ROOT / "agent" / "candidates.py").read_text(encoding="utf-8")
    for forbidden in ("runner_x == 7", "target_y == 6", "runner_x == 14"):
        assert_true(forbidden not in candidate_source, f"candidate routing has no {forbidden}")
    assert_equal(MAX_CANDIDATE_LIMIT, 20, "candidate limit has a fixed safety cap")


def run() -> None:
    check_runtime_boundary()
    check_geometry_candidates()
    check_target_relative_ladder_direction()
    check_loop_recovery()
    check_no_legacy_knowledge()
    print("backend geometry sanity ok")


if __name__ == "__main__":
    run()
