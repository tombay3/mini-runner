from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as app_module  # noqa: E402
from agent import AgentRequestError, validate_agent_request  # noqa: E402
from agent.candidates import (  # noqa: E402
    apply_prospective_horizontal_endpoint_safety,
    generate_candidates,
    is_action_guard_safe,
    ladder_alignment_score,
    limit_horizontal_ticks_under_guard_pressure,
)
from agent.prompt import format_state_summary  # noqa: E402
from agent.reasoning_tools import assess_guard_risk, get_movement_affordance  # noqa: E402
from agent.service import validate_or_fallback_candidate  # noqa: E402
from agent.loop_tools import build_loop_report, candidate_suppression_reason  # noqa: E402
from loader import _build_dataframes  # noqa: E402


def assert_equal(actual: Any, expected: Any, message: str) -> None:
    if actual != expected:
        raise AssertionError(f"{message}: expected {expected!r}, got {actual!r}")


def assert_true(value: Any, message: str) -> None:
    if not value:
        raise AssertionError(message)


def demo(level: int = 1, time: int = 32, state: int = 1) -> dict[str, Any]:
    return {
        "level": level,
        "ai": 4,
        "time": time,
        "state": state,
        "action": [0, 39, 8, 32],
        "goldDrop": [],
        "bornPos": [],
    }


def put_record(client, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.put("/api/recordings/1/1", json=payload)
    assert_equal(response.status_code, 200, response.get_data(as_text=True))
    return response.get_json()


def expect_bad_request(client, payload: dict[str, Any], message: str) -> None:
    response = client.put("/api/recordings/1/1", json=payload)
    assert_equal(response.status_code, 400, message)


def write_trace_run(trace_id: str) -> None:
    app_module.append_trace_step(
        trace_id,
        {
            "createdAt": f"2026-01-01T00:00:{len(trace_id):02d}.000Z",
            "playData": 1,
            "level": 1,
            "state": {"tick": 16},
            "candidates": [],
            "selectedCandidateId": None,
            "selectedCandidateKind": None,
            "validation": {},
            "action": {"keyCode": 39, "ticks": 8, "reason": "test"},
            "loopMonitor": {},
            "model": {"model": "openai:test", "provider": "openai"},
            "config": {},
        },
    )


def movement_history(
    candidate_ids: list[str], positions: list[tuple[int, int]], key_codes: list[int]
) -> list[dict[str, Any]]:
    history = []
    previous = positions[0]
    for candidate_id, position, key_code in zip(candidate_ids, positions, key_codes, strict=True):
        history.append(
            {
                "candidateId": candidate_id,
                "keyCode": key_code,
                "before": {"runner": {"x": previous[0], "y": previous[1]}, "goldCount": 5},
                "after": {"runner": {"x": position[0], "y": position[1]}, "goldCount": 5},
            }
        )
        previous = position
    return history


def loop_analysis() -> dict[str, Any]:
    return {
        "goldComplete": False,
        "routeAccess": {},
        "ladder": {},
        "movement": {"canMoveLeft": True, "canMoveRight": True},
        "primaryProgressTarget": {"x": 24, "y": 12},
        "rowLadders": [],
        "nearestGold": [],
    }


def check_loop_filter_regressions() -> None:
    right_ladder = "align_ladder_27_14_right"
    left_ladder = "align_ladder_4_14_left"
    progressing = movement_history(
        [right_ladder] * 4,
        [(19, 14), (20, 14), (22, 14), (23, 14)],
        [39] * 4,
    )
    progressing[0]["before"]["runner"]["x"] = 17
    report = build_loop_report(loop_analysis(), progressing)
    assert_true(not report["active"], "target progress remains outside loop handling")
    assert_true(report["evidence"]["targetProgress"], "target progress is recorded")
    assert_equal(report["suppress"]["candidateIds"], [], "progress suppresses nothing")

    reached = movement_history(
        [right_ladder] * 4,
        [(23, 14), (25, 14), (26, 14), (27, 14)],
        [39] * 4,
    )
    reached[0]["before"]["runner"]["x"] = 22
    report = build_loop_report(loop_analysis(), reached)
    assert_true(not report["active"], "reaching macro target clears loop warning")
    assert_true(report["evidence"]["targetReached"], "macro target completion is recorded")

    reached_after_reversals = movement_history(
        [right_ladder, right_ladder, left_ladder, right_ladder, left_ladder]
        + [right_ladder] * 3,
        [(23, 14), (25, 14), (23, 14), (25, 14), (23, 14), (25, 14), (26, 14), (27, 14)],
        [39, 39, 37, 39, 37, 39, 39, 39],
    )
    report = build_loop_report(loop_analysis(), reached_after_reversals)
    assert_true(not report["active"], "macro completion clears prior reversal warning")

    stuck = movement_history([right_ladder] * 4, [(20, 14)] * 4, [39] * 4)
    report = build_loop_report(loop_analysis(), stuck)
    assert_true(report["active"], "same candidate without movement activates loop filter")
    assert_equal(report["type"], "stationary_repeat", "stationary repeat type")
    assert_true("reason" not in report, "loop report omits redundant type-derived prose")
    assert_true(
        right_ladder in report["suppress"]["candidateIds"],
        "confirmed repeat suppresses the exact candidate id",
    )

    alternating = movement_history(
        [right_ladder, left_ladder, right_ladder, left_ladder],
        [(23, 14), (25, 14), (23, 14), (25, 14)],
        [39, 37, 39, 37],
    )
    report = build_loop_report(loop_analysis(), alternating)
    assert_true(not report["active"], "short alternation does not activate filtering")
    assert_equal(report["suppress"]["candidateIds"], [], "inactive filter suppresses nothing")
    trace_id = "trace-dashboard"
    recordings = {
        "records": {
            trace_id: {
                "id": trace_id,
                "traceId": trace_id,
                "source": "agent",
                "result": "failure",
                "playData": 1,
                "level": 1,
                "solver": {},
                "demo": {},
            }
        }
    }
    traces = {
        "version": 3,
        "runs": {
            trace_id: {
                "id": trace_id,
                "steps": [
                    {
                        "state": {
                            "gameState": "running",
                            "runner": {"x": 4, "y": 1},
                            "gold": {"remainingCount": 2},
                            "guardRisk": {"risk": "low"},
                        },
                        "candidates": [
                            {
                                "id": "requested",
                                "kind": "classic_gold_route",
                                "score": 100,
                                "target": {"x": 7, "y": 1},
                                "firstAction": {"keyCode": 39, "ticks": 8, "reason": "route"},
                            },
                            {
                                "id": "executed",
                                "kind": "retreat_from_guard",
                                "score": 110,
                                "target": None,
                                "firstAction": {"keyCode": 37, "ticks": 4, "reason": "retreat"},
                            },
                        ],
                        "selectedCandidateId": "executed",
                        "selectedCandidateKind": "retreat_from_guard",
                        "validation": {
                            "requestedCandidateId": "requested",
                            "selectedCandidateId": "executed",
                            "knownCandidate": True,
                            "fallbackUsed": True,
                            "fallbackReason": "selected action became unsafe",
                        },
                        "action": {"keyCode": 37, "ticks": 4, "reason": "retreat"},
                        "loopMonitor": {
                            "active": True,
                            "type": "horizontal_cycle",
                            "evidence": {},
                            "suppressedCandidates": [{"id": "blocked-route"}],
                        },
                    },
                    {
                        "state": {
                            "gameState": "running",
                            "runner": {"x": 3, "y": 1},
                            "gold": {"remainingCount": 2},
                            "guardRisk": {"risk": "medium"},
                        },
                        "candidates": [],
                        "selectedCandidateId": "wait_or_stop",
                        "selectedCandidateKind": "wait_or_stop",
                        "validation": {
                            "requestedCandidateId": "wait_or_stop",
                            "selectedCandidateId": "wait_or_stop",
                            "fallbackUsed": False,
                            "fallbackReason": None,
                        },
                        "action": {"keyCode": 32, "ticks": 2, "reason": "wait"},
                        "loopMonitor": {
                            "active": False,
                            "type": None,
                            "evidence": {},
                            "suppressedCandidates": [],
                        },
                    },
                ],
                "outcome": {
                    "result": "failure",
                    "reason": "fixture terminal",
                    "finalState": {
                        "gameState": "running",
                        "runner": {"x": 3, "y": 1},
                        "gold": {"remainingCount": 2},
                    },
                },
            }
        },
    }
    _runs_df, steps_df = _build_dataframes(recordings, traces)
    assert_equal(_runs_df.iloc[0]["pinned"], False, "legacy recording is unpinned")
    assert_equal(
        _runs_df.iloc[0]["averageCandidateCount"],
        1.0,
        "loader averages candidate count across trace steps",
    )
    first = steps_df.iloc[0]
    final = steps_df.iloc[1]
    assert_equal(first["requestedCandidateId"], "requested", "loader exposes raw model choice")
    assert_equal(first["selectedCandidateId"], "executed", "loader exposes executed choice")
    assert_equal(first["fallbackReason"], "selected action became unsafe", "loader exposes fallback")
    assert_equal(first["loop_suppressedIds"], "blocked-route", "loader exposes suppression")
    assert_equal(first["after_runner_x"], 3, "loader derives next-step runner outcome")
    assert_equal(first["after_risk_level"], "medium", "loader derives next-step risk outcome")
    assert_equal(final["after_runner_x"], 3, "loader uses final state for last action")
    assert_equal(final["terminal_result"], "failure", "loader exposes terminal result")
    assert_true("loop_reason" not in steps_df.columns, "loader omits redundant loop prose")

    confirmed_loop = movement_history(
        [right_ladder, left_ladder] * 3,
        [(23, 14), (25, 14), (23, 14), (25, 14), (23, 14), (25, 14)],
        [39, 37] * 3,
    )
    confirmed_report = build_loop_report(loop_analysis(), confirmed_loop)
    assert_true(confirmed_report["active"], "sustained alternation activates filter")
    assert_equal(confirmed_report["type"], "horizontal_cycle", "horizontal cycle type")
    assert_true(
        left_ladder in confirmed_report["suppress"]["candidateIds"],
        "confirmed non-progress route candidate is removed from the next selection",
    )
    guard_retreat_reason = candidate_suppression_reason(
        {
            "id": "retreat_from_guard_right",
            "kind": "retreat_from_guard",
            "firstAction": {"keyCode": 39, "ticks": 8},
        },
        confirmed_report,
    )
    assert_true(not guard_retreat_reason, "cycle filter preserves a safety retreat")
    wait_reason = candidate_suppression_reason(
        {
            "id": "wait_or_stop",
            "kind": "wait_or_stop",
            "firstAction": {"keyCode": 32, "ticks": 8},
        },
        confirmed_report,
    )
    assert_true(bool(wait_reason), "horizontal cycle suppresses non-progress waiting")

    progressing_safety_tug = movement_history(
        ["retreat_from_guard_right", left_ladder] * 3,
        [(12, 14), (11, 14), (12, 14), (13, 14), (14, 14), (13, 14)],
        [39, 37] * 3,
    )
    progressing_tug_report = build_loop_report(loop_analysis(), progressing_safety_tug)
    assert_true(
        not progressing_tug_report["active"],
        "route progress during a guard-driven horizontal tug is not mislabeled as a loop",
    )

    safety_retreat_tug = movement_history(
        [left_ladder, "retreat_from_guard_right"] * 3,
        [(13, 14), (14, 14), (13, 14), (14, 14), (13, 14), (14, 14)],
        [37, 39] * 3,
    )
    safety_tug_report = build_loop_report(loop_analysis(), safety_retreat_tug)
    assert_true(
        not safety_tug_report["active"],
        "a repeated guard-driven retreat is classified as safety movement, not a hard loop",
    )

    post_cycle_dig_wait = movement_history(
        [
            "collect_same_row_gold_7_12_left",
            "retreat_from_guard_right",
            "collect_same_row_gold_7_12_left",
            "retreat_from_guard_right",
            "collect_same_row_gold_7_12_left",
            "retreat_from_guard_right",
            "defensive_dig_dig_left",
            "wait_for_dig_completion_26_13_7_11",
            "wait_for_dig_completion_26_13_9_11",
        ],
        [(26, 12), (27, 12), (26, 12), (27, 12), (26, 12), (27, 12), (27, 12), (27, 12), (27, 12)],
        [37, 39, 37, 39, 37, 39, 90, 32, 32],
    )
    post_cycle_wait_report = build_loop_report(loop_analysis(), post_cycle_dig_wait)
    assert_true(
        not post_cycle_wait_report["active"],
        "dig-animation progress ends a preceding horizontal cycle signal",
    )

    post_cycle_emergency = movement_history(
        [
            "collect_same_row_gold_7_12_left",
            "retreat_from_guard_right",
            "collect_same_row_gold_7_12_left",
            "retreat_from_guard_right",
            "defensive_dig_dig_left",
            "wait_for_dig_completion_26_13_7_11",
            "wait_for_dig_completion_26_13_9_11",
            "emergency_hold_0_27_14_0_-18_up",
        ],
        [(26, 12), (27, 12), (26, 12), (27, 12), (27, 12), (27, 12), (27, 12), (27, 12)],
        [37, 39, 37, 39, 90, 32, 32, 32],
    )
    post_cycle_emergency_report = build_loop_report(loop_analysis(), post_cycle_emergency)
    assert_true(
        not post_cycle_emergency_report["active"],
        "bounded emergency safety hold is not suppressed by a stale horizontal cycle",
    )

    mixed_vertical_loop = movement_history(
        ["climb_ladder_27_13_up", "retreat_from_guard_down"] * 3,
        [(27, 13), (27, 12), (27, 13), (27, 12), (27, 13), (27, 12)],
        [38, 40] * 3,
    )
    vertical_analysis = loop_analysis()
    vertical_analysis["primaryProgressTarget"] = {"x": 24, "y": 11, "direction": "left"}
    vertical_report = build_loop_report(vertical_analysis, mixed_vertical_loop)
    assert_equal(
        vertical_report["type"],
        "vertical_cycle",
        "mixed climb/retreat vertical cycle is detected",
    )
    assert_true(
        bool(vertical_report["suppress"]["directions"]),
        "vertical cycle suppresses at least one reversing ladder direction",
    )

    three_row_vertical_loop = movement_history(
        [
            "retreat_from_guard_down",
            "retreat_from_guard_down",
            "climb_ladder_2_8_up",
            "climb_ladder_2_7_up",
        ]
        * 2,
        [(2, 7), (2, 8), (2, 7), (2, 6)] * 2,
        [40, 40, 38, 38] * 2,
    )
    targetless_vertical_analysis = loop_analysis()
    targetless_vertical_analysis["primaryProgressTarget"] = None
    targetless_vertical_analysis["movement"] = {
        "canMoveLeft": True,
        "canMoveRight": True,
    }
    three_row_report = build_loop_report(
        targetless_vertical_analysis, three_row_vertical_loop
    )
    assert_equal(
        three_row_report["type"],
        "vertical_cycle",
        "multi-action three-row ladder cycle is detected from direction runs",
    )
    assert_equal(
        three_row_report["suppress"]["directions"],
        ["up"],
        "targetless carried-gold cycle suppresses the reversing progress climb",
    )
    climb_reason = candidate_suppression_reason(
        {
            "id": "climb_ladder_2_8_up",
            "kind": "climb_ladder",
            "firstAction": {"keyCode": 38, "ticks": 6},
        },
        three_row_report,
    )
    assert_true(bool(climb_reason), "three-row loop blocks the upward ladder reversal")
    retreat_reason = candidate_suppression_reason(
        {
            "id": "retreat_from_guard_down",
            "kind": "retreat_from_guard",
            "firstAction": {"keyCode": 40, "ticks": 6},
        },
        three_row_report,
    )
    assert_true(not retreat_reason, "vertical recovery preserves the guard-driven retreat")

    carried_descent_cycle = movement_history(
        ["descend_route_7_3_down", "climb_ladder_7_3_up"] * 3,
        [(7, 3), (7, 1)] * 3,
        [40, 38] * 3,
    )
    carried_descent_analysis = loop_analysis()
    carried_descent_analysis["primaryProgressTarget"] = None
    carried_descent_report = build_loop_report(
        carried_descent_analysis, carried_descent_cycle
    )
    assert_equal(
        carried_descent_report["type"],
        "vertical_cycle",
        "guard-carried descend/climb cycle is detected",
    )
    assert_true(
        "up" in carried_descent_report["suppress"]["directions"],
        "guard-carried vertical recovery suppresses the upward reversal",
    )

    stationary_wait_hold = movement_history(
        ["wait_or_stop", "emergency_hold_1_7_1_0_0_right"] * 4,
        [(7, 1)] * 8,
        [32] * 8,
    )
    stationary_wait_hold_report = build_loop_report(
        loop_analysis(), stationary_wait_hold
    )
    assert_equal(
        stationary_wait_hold_report["type"],
        "stationary_repeat",
        "emergency fallback does not erase an alternating same-tile wait loop",
    )

    floor_wait_history = movement_history(
        [f"wait_for_floor_refill_24_13_0_{value}" for value in (40, 48, 56, 64, 72, 80)],
        [(25, 12)] * 6,
        [32] * 6,
    )
    floor_wait_report = build_loop_report(loop_analysis(), floor_wait_history)
    assert_true(not floor_wait_report["active"], "timed floor refill is environment progress")

    inactive_analysis = loop_analysis()
    inactive_analysis.update(
        {
            "runner": {"x": 25, "y": 14},
            "gold": {"remainingCount": 5, "visiblePositions": []},
            "risk": {"risk": "low", "pressureGuard": None, "nearbyGuards": []},
            "routeAccess": {},
            "ladder": {"detail": "ladder nearby"},
            "loopReport": report,
        }
    )
    state_prompt = format_state_summary(
        {"playData": 1, "level": 1, "gameStateName": "running"}, inactive_analysis
    )
    assert_true("loop={active:False" in state_prompt, "state exposes compact inactive loop status")

    assert_true(
        ladder_alignment_score(5, god_mode=False, fine_align=False, loop_target=False)
        > ladder_alignment_score(18, god_mode=False, fine_align=False, loop_target=False),
        "near ladder outranks distant ladder",
    )
    assert_true(
        ladder_alignment_score(1, god_mode=False, fine_align=True, loop_target=False)
        > ladder_alignment_score(2, god_mode=False, fine_align=False, loop_target=False),
        "fine alignment remains highest near target",
    )


def check_guard_safety_regressions() -> None:
    snapshot = {
        "runner": {"x": 25, "y": 12},
        "guards": [{"x": 22, "y": 12, "actionName": "right"}],
        "terrainGrid": [" " * 28 for _ in range(16)],
    }
    risk = assess_guard_risk(snapshot)
    guard = risk["pressureGuard"]
    assert_equal(risk["risk"], "high", "three-tile same-row guard is high risk")
    assert_equal(guard["relativeX"], "left", "guard side is relative position")
    assert_equal(guard["motion"], "right", "guard motion is separate from side")
    assert_true(guard["closing"], "right-moving guard on left is closing")
    assert_true("direction" not in guard, "ambiguous guard direction field is absent")
    assert_equal(guard["relativeY"], "same", "guard vertical relation")

    analysis = {"godMode": False, "risk": risk}
    assert_true(
        not is_action_guard_safe({"keyCode": 37}, analysis),
        "normal-mode movement toward high-risk guard is unsafe",
    )
    assert_true(
        is_action_guard_safe({"keyCode": 39}, analysis),
        "normal-mode movement away from high-risk guard is safe",
    )
    adjacent_climb_out_analysis = {
        "godMode": False,
        "risk": {
            "risk": "critical",
            "pressureGuard": {
                "distance": 1,
                "risk": "critical",
                "relativeX": "left",
                "relativeY": "same",
                "motion": "climb_out",
            },
            "nearbyGuards": [],
        },
    }
    assert_true(
        not is_action_guard_safe({"keyCode": 38}, adjacent_climb_out_analysis),
        "runner does not follow an adjacent climbing guard upward into its escape lane",
    )
    assert_true(
        is_action_guard_safe({"keyCode": 40}, adjacent_climb_out_analysis),
        "runner may continue down away from an adjacent climbing guard",
    )
    medium_analysis = {
        "godMode": False,
        "risk": {
            "risk": "medium",
            "pressureGuard": {
                "x": 20,
                "distance": 4,
                "risk": "medium",
                "relativeX": "left",
                "relativeY": "same",
            },
            "nearbyGuards": [],
        },
    }
    assert_true(
        not is_action_guard_safe({"keyCode": 37}, medium_analysis),
        "movement toward a medium-risk same-row guard is unsafe",
    )
    assert_equal(
        limit_horizontal_ticks_under_guard_pressure(
            {"keyCode": 39, "ticks": 8, "reason": "retreat"}, analysis
        )["ticks"],
        4,
        "horizontal guard-pressure burst is shortened",
    )
    assert_equal(
        limit_horizontal_ticks_under_guard_pressure(
            {"keyCode": 90, "ticks": 8, "reason": "dig"}, analysis
        )["ticks"],
        8,
        "defensive dig duration is preserved",
    )
    edge_endpoint_analysis = {
        "godMode": False,
        "runner": {"x": 26, "y": 12, "xOffset": 8, "yOffset": 0},
        "risk": {
            "risk": "high",
            "pressureGuard": {
                "risk": "high",
                "closing": True,
                "relativeX": "left",
                "relativeY": "below",
            },
        },
        "movement": {"terrainHeight": 16, "details": {"right": {}}},
    }
    assert_true(
        apply_prospective_horizontal_endpoint_safety(
            {"keyCode": 39, "ticks": 4, "reason": "retreat right"},
            edge_endpoint_analysis,
            "retreat_from_guard",
        )
        is None,
        "right-edge regression rejects an off-center retreat with a closing guard behind",
    )
    bottom_hole_endpoint_analysis = {
        "godMode": False,
        "runner": {"x": 20, "y": 14, "xOffset": -8, "yOffset": 0},
        "risk": {
            "risk": "medium",
            "pressureGuard": {
                "risk": "medium",
                "closing": True,
                "relativeX": "left",
                "relativeY": "same",
            },
        },
        "movement": {
            "terrainHeight": 16,
            "details": {
                "right": {
                    "openHole": {
                        "distance": 2,
                        "x": 22,
                        "y": 15,
                        "occupiedByTrappedGuard": False,
                    }
                }
            },
        },
    }
    centered_before_hole = apply_prospective_horizontal_endpoint_safety(
        {"keyCode": 39, "ticks": 4, "reason": "route right"},
        bottom_hole_endpoint_analysis,
        "classic_gold_route",
    )
    assert_equal(
        centered_before_hole["ticks"] if centered_before_hole else None,
        1,
        "bottom-hole regression shortens the route to center on the safe tile",
    )
    assert_true(
        "stop centered" in str((centered_before_hole or {}).get("reason")),
        "shortened endpoint action explains the prospective safety stop",
    )
    nonclosing_endpoint = apply_prospective_horizontal_endpoint_safety(
        {"keyCode": 39, "ticks": 4, "reason": "route right"},
        {
            **bottom_hole_endpoint_analysis,
            "risk": {
                "risk": "medium",
                "pressureGuard": {
                    "risk": "medium",
                    "closing": False,
                    "relativeX": "left",
                    "relativeY": "same",
                },
            },
        },
        "classic_gold_route",
    )
    assert_equal(
        (nonclosing_endpoint or {}).get("ticks"),
        4,
        "nonclosing guard does not shorten ordinary bottom-hole routing",
    )
    assert_true(
        is_action_guard_safe({"keyCode": 37}, {**analysis, "godMode": True}),
        "god mode permits progress through guard contact",
    )
    god_candidates, _god_analysis = generate_candidates(
        {
            "playData": 1,
            "level": 1,
            "gameStateName": "running",
            "godMode": True,
            "runner": {"x": 10, "y": 10, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
            "guards": [],
            "gold": {
                "complete": False,
                "remainingCount": 1,
                "visiblePositions": [{"x": 15, "y": 5}],
                "carriedByGuards": [],
            },
            "terrainGrid": [" " * 28 for _ in range(16)],
        },
        [],
    )
    assert_true(
        "god_mode_progress" in {candidate["kind"] for candidate in god_candidates},
        "god mode retains direct progress toward off-row targets",
    )

    prompt_analysis = {
        "runner": {"x": 25, "y": 12},
        "gold": {"remainingCount": 4, "visiblePositions": []},
        "risk": risk,
        "movement": {},
        "ladder": {},
        "routeAccess": {},
        "loopReport": {"active": False, "type": None},
    }
    state_prompt = format_state_summary(
        {"playData": 1, "level": 1, "gameStateName": "running"}, prompt_analysis
    )
    assert_true("guardRisk=high" in state_prompt, "prompt exposes compact guard risk")
    assert_true("pressureGuard" not in state_prompt, "prompt omits backend guard geometry")

    ladder_terrain = [" " * 28 for _ in range(16)]
    ladder_terrain[5] = "       H" + " " * 20
    ladder_terrain[6] = "       H" + " " * 20
    vertical_snapshot = {
        "runner": {"x": 7, "y": 6},
        "guards": [{"id": 2, "x": 7, "y": 5, "actionName": "down"}],
        "terrainGrid": ladder_terrain,
        "godMode": False,
    }
    vertical_risk = assess_guard_risk(vertical_snapshot)
    assert_equal(vertical_risk["pressureGuard"]["relativeY"], "above", "vertical guard relation")
    movement = get_movement_affordance(vertical_snapshot)
    assert_true(not movement["canMoveUp"], "normal mode cannot climb into a guard-occupied tile")
    assert_equal(movement["details"]["up"]["reason"], "occupied by guard", "blocked climb reason")
    god_movement = get_movement_affordance({**vertical_snapshot, "godMode": True})
    assert_true(god_movement["canMoveUp"], "god mode can enter a guard-occupied ladder tile")

    trapped_risk = assess_guard_risk(
        {
            "runner": {"x": 27, "y": 12},
            "guards": [
                {"id": 1, "x": 24, "y": 13, "actionName": "in_hole"},
                {"id": 2, "x": 15, "y": 12, "actionName": "right"},
            ],
            "terrainGrid": [" " * 28 for _ in range(16)],
        }
    )
    assert_equal(trapped_risk["risk"], "low", "contained guard is low immediate pressure")
    assert_equal(
        trapped_risk["nearbyGuards"][0]["motion"],
        "in_hole",
        "geometrically nearest contained guard remains observable",
    )

    cross_row_analysis = {"godMode": False, "risk": vertical_risk}
    assert_true(
        not is_action_guard_safe({"keyCode": 38}, cross_row_analysis),
        "normal mode does not climb toward a high-risk cross-row guard",
    )
    assert_equal(
        limit_horizontal_ticks_under_guard_pressure(
            {"keyCode": 39, "ticks": 8, "reason": "cross-row retreat"}, cross_row_analysis
        )["ticks"],
        4,
        "cross-row guard pressure shortens horizontal bursts",
    )
    mixed_row_risk = {
        "risk": "high",
        "pressureGuard": {
            "distance": 2,
            "risk": "high",
            "relativeX": "left",
            "relativeY": "below",
        },
        "nearbyGuards": [],
    }
    assert_true(
        not is_action_guard_safe(
            {"keyCode": 37}, {"godMode": False, "risk": mixed_row_risk, "runner": {"action": "stop"}}
        ),
        "near high-risk cross-row guard outranks a farther low-risk same-row guard",
    )
    assert_true(
        is_action_guard_safe(
            {"keyCode": 32}, {"godMode": False, "risk": mixed_row_risk, "runner": {"action": "fall"}}
        ),
        "neutral input remains available while falling under guard pressure",
    )
    assert_true(
        is_action_guard_safe(
            {"keyCode": 32},
            {"godMode": False, "risk": mixed_row_risk, "runner": {"action": "stop"}},
            candidate_kind="emergency_hold",
        ),
        "explicit emergency hold advances a fully blocked state",
    )
    medium_cross_row_risk = {
        "risk": "medium",
        "pressureGuard": {
            "distance": 5,
            "risk": "medium",
            "relativeX": "left",
            "relativeY": "below",
        },
    }
    assert_true(
        is_action_guard_safe(
            {"keyCode": 37},
            {"godMode": False, "risk": medium_cross_row_risk, "runner": {"action": "stop"}},
        ),
        "medium cross-row pressure permits bounded horizontal progress",
    )

    terrain = [
        "                  S         ",
        "                  S         ",
        "#######H#######   S         ",
        "       H----------S         ",
        "       H    ##H   #######H##",
        "       H    ##H          H  ",
        "       H    ##H          H  ",
        "##H#####    ########H#######",
        "  H                 H       ",
        "  H                 H       ",
        "#########H##########H       ",
        "         H          H       ",
        "         H----------H       ",
        "    H######         #######H",
        "    H                      H",
        "############################",
    ]
    pressure_snapshot = {
        "playData": 1,
        "level": 1,
        "gameStateName": "running",
        "godMode": False,
        "runner": {"x": 24, "y": 12, "xOffset": 0, "yOffset": 0, "actionName": "left"},
        "guards": [{"id": 0, "x": 20, "y": 12, "actionName": "right"}],
        "gold": {
            "complete": False,
            "remainingCount": 4,
            "visiblePositions": [{"x": 7, "y": 12}, {"x": 4, "y": 1}, {"x": 23, "y": 3}],
            "carriedByGuards": [],
        },
        "goldComplete": False,
        "goldCount": 4,
        "terrainGrid": terrain,
    }

    god_route_cycle_history = movement_history(
        ["god_mode_progress_4_1_left", "align_ladder_7_6_right"] * 4,
        [(4, 6), (5, 6)] * 4,
        [37, 39] * 4,
    )
    god_route_cycle_snapshot = {
        **pressure_snapshot,
        "godMode": True,
        "runner": {"x": 5, "y": 6, "xOffset": 8, "yOffset": 0, "actionName": "right"},
        "guards": [],
        "gold": {
            "complete": False,
            "remainingCount": 2,
            "visiblePositions": [{"x": 4, "y": 1}, {"x": 23, "y": 3}],
            "carriedByGuards": [],
        },
        "goldCount": 2,
    }
    god_route_candidates, god_route_analysis = generate_candidates(
        god_route_cycle_snapshot, god_route_cycle_history
    )
    god_route_ids = {candidate["id"] for candidate in god_route_candidates}
    assert_true(
        not god_route_analysis["loopReport"]["active"],
        "god-route fixture reproduces the trace state where local ladder progress hid the cycle",
    )
    assert_true(
        "align_ladder_7_6_right" in god_route_ids,
        "god mode retains the structured ladder route toward upper gold",
    )
    assert_true(
        "god_mode_progress_4_1_left" not in god_route_ids,
        "direct god-mode fallback cannot reverse a viable ladder route",
    )

    candidates, _analysis = generate_candidates(pressure_snapshot, [])
    assert_true(
        all(
            set(candidate) == {"id", "kind", "score", "target", "firstAction"}
            for candidate in candidates
        ),
        "candidate schema stays minimal",
    )
    signatures = [
        (candidate["firstAction"]["keyCode"], candidate["firstAction"]["ticks"])
        for candidate in candidates
    ]
    assert_equal(len(signatures), len(set(signatures)), "executed actions are deduplicated")
    candidate_ids = {candidate["id"] for candidate in candidates}
    assert_true(
        "collect_same_row_gold_7_12_left" not in candidate_ids,
        "medium-risk progress toward guard is not offered",
    )
    assert_true(
        "defensive_dig_dig_left" in candidate_ids,
        "legal defensive dig remains available",
    )
    retreat = next(
        candidate for candidate in candidates if candidate["id"] == "retreat_from_guard_right"
    )
    assert_equal(retreat["firstAction"]["ticks"], 4, "retreat is reassessed after four ticks")
    assert_true(
        "closing" in retreat["firstAction"]["reason"]
        and "guard may follow" in retreat["firstAction"]["reason"],
        "retreat explains guard motion without promising increased distance",
    )
    assert_true(
        "reassess" in retreat["firstAction"]["reason"].lower(),
        "retreat is framed as a short reposition followed by reassessment",
    )

    edge_endpoint_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 26, "y": 12, "xOffset": 8, "yOffset": 0, "actionName": "left"},
        "guards": [
            {"id": 1, "x": 25, "y": 14, "xOffset": 16, "yOffset": 0, "actionName": "right"}
        ],
        "gold": {
            "complete": False,
            "remainingCount": 1,
            "visiblePositions": [{"x": 7, "y": 12}],
            "carriedByGuards": [],
        },
        "goldCount": 1,
    }
    edge_endpoint_candidates, edge_endpoint_generated_analysis = generate_candidates(
        edge_endpoint_snapshot, []
    )
    assert_equal(
        edge_endpoint_generated_analysis["risk"]["risk"],
        "high",
        "right-edge endpoint fixture preserves the death trace pressure class",
    )
    edge_endpoint_retreat = next(
        candidate
        for candidate in edge_endpoint_candidates
        if candidate["id"] == "retreat_from_guard_right"
    )
    assert_equal(
        edge_endpoint_retreat["firstAction"]["ticks"],
        4,
        "retreat remains eligible when the projected edge tile has a ladder escape",
    )
    assert_true(
        "emergency_hold" not in {candidate["kind"] for candidate in edge_endpoint_candidates},
        "usable right-edge ladder escape is preferred over holding in the approach column",
    )

    bottom_hole_grid = terrain.copy()
    bottom_hole_floor = list(bottom_hole_grid[15])
    bottom_hole_floor[22] = " "
    bottom_hole_grid[15] = "".join(bottom_hole_floor)
    bottom_hole_endpoint_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 20, "y": 14, "xOffset": -8, "yOffset": 0, "actionName": "right"},
        "guards": [
            {"id": 2, "x": 16, "y": 14, "xOffset": 0, "yOffset": 0, "actionName": "right"}
        ],
        "gold": {
            "complete": False,
            "remainingCount": 1,
            "visiblePositions": [{"x": 23, "y": 3}],
            "carriedByGuards": [],
        },
        "goldCount": 1,
        "grid": bottom_hole_grid,
        "openHoles": [{"x": 22, "y": 15, "frameIndex": 0, "frameTime": 130}],
    }
    bottom_hole_candidates, bottom_hole_generated_analysis = generate_candidates(
        bottom_hole_endpoint_snapshot, []
    )
    assert_equal(
        bottom_hole_generated_analysis["risk"]["risk"],
        "medium",
        "bottom-hole endpoint fixture preserves the death trace pressure class",
    )
    bottom_hole_route = next(
        candidate
        for candidate in bottom_hole_candidates
        if candidate["id"] == "classic_gold_route_27_14_right"
    )
    assert_equal(
        bottom_hole_route["firstAction"]["ticks"],
        1,
        "full generator centers before the bottom hole instead of ending off-center beside it",
    )

    adjacent_bottom_hole_snapshot = {
        **bottom_hole_endpoint_snapshot,
        "runner": {"x": 21, "y": 14, "xOffset": -16, "yOffset": 0, "actionName": "stop"},
        "guards": [
            {"id": 2, "x": 20, "y": 14, "xOffset": -8, "yOffset": 0, "actionName": "right"}
        ],
    }
    adjacent_bottom_hole_candidates, adjacent_bottom_hole_analysis = generate_candidates(
        adjacent_bottom_hole_snapshot, []
    )
    adjacent_bottom_hole_route = next(
        candidate
        for candidate in adjacent_bottom_hole_candidates
        if candidate["id"] == "classic_gold_route_27_14_right"
    )
    assert_equal(
        adjacent_bottom_hole_analysis["risk"]["risk"],
        "critical",
        "adjacent bottom-hole fixture preserves the live trace pressure class",
    )
    assert_equal(
        adjacent_bottom_hole_route["firstAction"]["ticks"],
        2,
        "sub-tile motion may center without entering the adjacent bottom hole",
    )
    assert_true(
        "emergency_hold"
        not in {candidate["kind"] for candidate in adjacent_bottom_hole_candidates},
        "safe centering prevents the adjacent-hole emergency-hold failure",
    )
    adjacent_bottom_hole_selected, adjacent_bottom_hole_validation = (
        validate_or_fallback_candidate(
            {"choice": {"candidateId": adjacent_bottom_hole_route["id"]}},
            adjacent_bottom_hole_candidates,
            adjacent_bottom_hole_analysis,
        )
    )
    assert_equal(
        adjacent_bottom_hole_selected["id"],
        adjacent_bottom_hole_route["id"],
        "post-model validation preserves the safe sub-tile centering candidate",
    )
    assert_true(
        not adjacent_bottom_hole_validation["fallbackUsed"],
        "post-model validation shares the prospective endpoint horizon",
    )

    carried_gold_trap_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 4, "y": 6, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "guards": [
            {
                "id": 1,
                "x": 7,
                "y": 6,
                "xOffset": -8,
                "yOffset": -6,
                "actionName": "left",
                "hasGold": 12,
            }
        ],
        "gold": {
            "complete": False,
            "remainingCount": 1,
            "visiblePositions": [],
            "carriedByGuards": [{"id": 1, "x": 7, "y": 6, "hasGold": 12}],
        },
        "goldCount": 1,
    }
    carried_trap_candidates, carried_trap_analysis = generate_candidates(
        carried_gold_trap_snapshot, []
    )
    assert_equal(
        carried_trap_analysis["risk"]["risk"],
        "high",
        "carried-gold trap fixture matches the trace pressure class",
    )
    assert_true(
        "defensive_dig_dig_right"
        in {candidate["id"] for candidate in carried_trap_candidates},
        "closing gold carrier exposes the prepared right-side trap",
    )

    row_one_offset_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 4, "y": 1, "xOffset": -8, "yOffset": 0, "actionName": "stop"},
        "guards": [
            {"id": 0, "x": 9, "y": 10, "xOffset": 0, "yOffset": -20, "actionName": "up"},
            {"id": 1, "x": 13, "y": 12, "xOffset": 8, "yOffset": 0, "actionName": "right"},
            {"id": 2, "x": 20, "y": 6, "xOffset": -8, "yOffset": 12, "actionName": "left"},
        ],
        "gold": {
            "complete": False,
            "remainingCount": 1,
            "visiblePositions": [{"x": 23, "y": 3}],
            "carriedByGuards": [],
        },
        "goldCount": 1,
    }
    row_one_offset_candidates, row_one_offset_analysis = generate_candidates(
        row_one_offset_snapshot, []
    )
    assert_equal(
        row_one_offset_analysis["risk"]["risk"],
        "low",
        "row-1 offset regression preserves the live failure's low pressure class",
    )
    assert_true(
        "classic_gold_route_7_1_right"
        in {candidate["id"] for candidate in row_one_offset_candidates},
        "row-1 route remains available immediately after collecting offset gold",
    )
    assert_true(
        "retreat_from_guard_left"
        not in {candidate["id"] for candidate in carried_trap_candidates},
        "decisive distance-three trap withholds the loop-entering retreat",
    )
    monotonic_retreat_history = movement_history(
        ["retreat_from_guard_right"] * 6,
        [(20, 12), (21, 12), (22, 12), (23, 12), (24, 12), (25, 12)],
        [39] * 6,
    )
    _retreat_candidates, retreat_analysis = generate_candidates(
        pressure_snapshot,
        monotonic_retreat_history,
    )
    assert_true(
        not retreat_analysis["loopReport"]["active"],
        "monotonic guard retreat is treated as environment progress",
    )

    tied_pressure_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 6, "y": 12, "xOffset": -8, "yOffset": 0, "actionName": "left"},
        "guards": [
            {"id": 0, "x": 4, "y": 13, "xOffset": 0, "yOffset": 8, "actionName": "up"},
            {"id": 2, "x": 9, "y": 12, "xOffset": 0, "yOffset": -15, "actionName": "down"},
        ],
    }
    tied_pressure_candidates, tied_pressure_analysis = generate_candidates(
        tied_pressure_snapshot, []
    )
    assert_equal(
        tied_pressure_analysis["risk"]["pressureGuard"]["id"],
        2,
        "equal-risk pressure prioritizes the same-row guard over a cross-row guard",
    )
    assert_true(
        "retreat_from_guard_left"
        in {candidate["id"] for candidate in tied_pressure_candidates},
        "same-row pressure tie exposes retreat away from imminent row contact",
    )

    explicit_hole_snapshot = {
        **tied_pressure_snapshot,
        "guards": [
            {"id": 2, "x": 7, "y": 12, "xOffset": 0, "yOffset": 0, "actionName": "left"},
        ],
        "openHoles": [{"x": 5, "y": 13, "frameIndex": 0, "frameTime": 10}],
    }
    explicit_hole_candidates, _explicit_hole_analysis = generate_candidates(
        explicit_hole_snapshot, []
    )
    assert_true(
        "retreat_from_guard_left"
        not in {candidate["id"] for candidate in explicit_hole_candidates},
        "ordinary retreat cannot enter an explicit legacy open hole",
    )

    supported_hole_snapshot = {
        **explicit_hole_snapshot,
        "guards": [
            {"id": 0, "x": 5, "y": 13, "xOffset": 0, "yOffset": 0, "actionName": "in_hole"},
            {"id": 2, "x": 7, "y": 12, "xOffset": 0, "yOffset": 0, "actionName": "left"},
        ],
    }
    supported_hole_candidates, supported_hole_analysis = generate_candidates(
        supported_hole_snapshot, []
    )
    assert_true(
        supported_hole_analysis["movement"]["details"]["left"]["openHole"][
            "occupiedByTrappedGuard"
        ],
        "movement analysis marks an open hole supported by a trapped guard",
    )
    assert_true(
        "retreat_from_guard_left"
        in {candidate["id"] for candidate in supported_hole_candidates},
        "ordinary retreat can cross a hole while a fully trapped guard supports it",
    )

    edge_intercept_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 27, "y": 12, "xOffset": 0, "yOffset": 0, "actionName": "right"},
        "guards": [
            {"id": 2, "x": 26, "y": 14, "xOffset": -8, "yOffset": 0, "actionName": "right"},
        ],
    }
    edge_intercept_candidates, _edge_intercept_analysis = generate_candidates(
        edge_intercept_snapshot, []
    )
    edge_escape = next(
        candidate
        for candidate in edge_intercept_candidates
        if candidate["id"] == "evade_edge_ladder_left"
    )
    assert_equal(
        edge_escape["firstAction"]["keyCode"],
        37,
        "right-edge runner steps left before a below guard enters the ladder column",
    )
    assert_true(
        "defensive_dig_dig_left"
        not in {candidate["id"] for candidate in edge_intercept_candidates},
        "edge-ladder evasion is exclusive over a conflicting defensive dig",
    )

    fully_blocked_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 0, "y": 14, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "guards": [
            {"id": 0, "x": 1, "y": 14, "xOffset": -8, "yOffset": 0, "actionName": "left"}
        ],
    }
    fully_blocked_candidates, _fully_blocked_analysis = generate_candidates(
        fully_blocked_snapshot, []
    )
    assert_equal(
        {candidate["kind"] for candidate in fully_blocked_candidates},
        {"emergency_hold"},
        "fully blocked same-row contact produces a bounded hold instead of an empty set",
    )

    one_sided_hole_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 25, "y": 12, "xOffset": 0, "yOffset": 0, "actionName": "left"},
        "guards": [
            {"id": 2, "x": 25, "y": 13, "xOffset": 0, "yOffset": 0, "actionName": "in_hole"},
            {"id": 0, "x": 26, "y": 14, "xOffset": 0, "yOffset": 0, "actionName": "right"},
        ],
        "openHoles": [{"x": 24, "y": 13, "frameIndex": 0, "frameTime": 16}],
    }
    one_sided_candidates, _one_sided_analysis = generate_candidates(
        one_sided_hole_snapshot, []
    )
    hole_evade = next(
        candidate
        for candidate in one_sided_candidates
        if candidate["id"] == "evade_open_hole_right"
    )
    assert_equal(
        hole_evade["firstAction"]["keyCode"],
        39,
        "runner steps onto solid floor instead of digging a second adjacent hole",
    )

    descending_guard_hole_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 25, "y": 14, "xOffset": 0, "yOffset": 0, "actionName": "fall"},
        "guards": [
            {"id": 2, "x": 27, "y": 13, "xOffset": 0, "yOffset": -10, "actionName": "down"},
        ],
        "openHoles": [{"x": 24, "y": 15, "frameIndex": 0, "frameTime": 128}],
    }
    descending_guard_candidates, descending_guard_analysis = generate_candidates(
        descending_guard_hole_snapshot, []
    )
    descending_guard_ids = {
        candidate["id"] for candidate in descending_guard_candidates
    }
    assert_true(
        descending_guard_analysis["dig"]["right"]["guardCouldFall"],
        "centered runner can prepare a bottom-row trap for a guard descending onto the row",
    )
    assert_true(
        "defensive_dig_dig_right" in descending_guard_ids,
        "descending guard exposes a proactive trap before same-row contact",
    )
    assert_true(
        "evade_open_hole_right" not in descending_guard_ids,
        "one-sided hole escape does not move toward an imminently landing guard",
    )
    assert_equal(
        descending_guard_candidates[0]["id"],
        "defensive_dig_dig_right",
        "proactive landing trap outranks the floor-refill wait",
    )

    off_center_dig_snapshot = {
        **descending_guard_hole_snapshot,
        "runner": {"x": 25, "y": 14, "xOffset": 16, "yOffset": 0, "actionName": "left"},
    }
    off_center_candidates, off_center_analysis = generate_candidates(
        off_center_dig_snapshot, []
    )
    assert_true(
        not off_center_analysis["dig"]["right"]["canDefensiveDig"],
        "off-center runner is not reported as able to start a defensive dig",
    )
    assert_true(
        "defensive_dig_dig_right"
        not in {candidate["id"] for candidate in off_center_candidates},
        "off-center defensive dig is filtered before model selection",
    )

    active_dig_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 16, "y": 14, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "guards": [
            {"id": 0, "x": 12, "y": 14, "xOffset": 8, "yOffset": 0, "actionName": "right"},
            {"id": 2, "x": 19, "y": 14, "xOffset": -16, "yOffset": 0, "actionName": "left"},
        ],
        "activeDig": {
            "active": True,
            "x": 17,
            "y": 15,
            "direction": "right",
            "frameIndex": 8,
            "frameCount": 11,
            "remainingFrames": 3,
        },
    }
    active_dig_loop_history = movement_history(
        ["align_ladder_27_14_right", "align_ladder_4_14_left"] * 3,
        [(16, 14), (17, 14), (16, 14), (17, 14), (16, 14), (17, 14)],
        [39, 37] * 3,
    )
    active_dig_candidates, active_dig_analysis = generate_candidates(
        active_dig_snapshot, active_dig_loop_history
    )
    dig_wait = next(
        candidate
        for candidate in active_dig_candidates
        if candidate["kind"] == "wait_for_dig_completion"
    )
    assert_equal(active_dig_analysis["activeDig"]["frameIndex"], 8, "active dig is analyzed")
    assert_equal(dig_wait["firstAction"]["ticks"], 2, "active dig advances in bounded increments")
    assert_equal(
        {candidate["kind"] for candidate in active_dig_candidates},
        {"wait_for_dig_completion"},
        "active dig completion is exclusive until the future hole becomes observable",
    )
    assert_true(
        dig_wait["id"] not in {
            item["id"] for item in active_dig_analysis["loopReport"]["suppressedCandidates"]
        },
        "active dig completion remains eligible during a horizontal cycle",
    )

    separated_trap_grid = terrain.copy()
    separated_trap_floor = list(separated_trap_grid[13])
    separated_trap_floor[21] = " "
    separated_trap_floor[24] = " "
    separated_trap_grid[13] = "".join(separated_trap_floor)
    separated_trap_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 23, "y": 12, "xOffset": -8, "yOffset": 0, "actionName": "right"},
        "guards": [
            {"id": 1, "x": 24, "y": 13, "xOffset": 0, "yOffset": 0, "actionName": "in_hole"},
            {"id": 2, "x": 20, "y": 12, "xOffset": -8, "yOffset": 0, "actionName": "right"},
        ],
        "grid": separated_trap_grid,
        "openHoles": [
            {"x": 21, "y": 13, "frameIndex": 0, "frameTime": 4},
            {"x": 24, "y": 13, "frameIndex": 0, "frameTime": 76},
        ],
    }
    separated_trap_candidates, _separated_trap_analysis = generate_candidates(
        separated_trap_snapshot, []
    )
    separated_kinds = {candidate["kind"] for candidate in separated_trap_candidates}
    assert_true(
        "wait_for_trap_resolution" in separated_kinds,
        "existing hole between runner and pressure guard exposes a bounded trap hold",
    )
    separated_wait = next(
        candidate
        for candidate in separated_trap_candidates
        if candidate["kind"] == "wait_for_trap_resolution"
    )
    assert_equal(
        separated_wait["firstAction"]["ticks"],
        4,
        "medium-range trap polling advances four ticks",
    )
    assert_true(
        "defensive_dig" not in separated_kinds,
        "existing separating trap suppresses a redundant adjacent defensive dig",
    )
    assert_equal(
        separated_kinds,
        {"wait_for_trap_resolution"},
        "existing separating trap makes bounded environment resolution exclusive",
    )

    supported_bridge_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 23, "y": 14, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "guards": [
            {"id": 0, "x": 21, "y": 14, "xOffset": 8, "yOffset": 0, "actionName": "right"},
            {"id": 1, "x": 24, "y": 15, "xOffset": 0, "yOffset": 0, "actionName": "in_hole"},
            {"id": 2, "x": 22, "y": 15, "xOffset": 0, "yOffset": 0, "actionName": "in_hole"},
        ],
        "openHoles": [
            {"x": 22, "y": 15, "frameIndex": 0, "frameTime": 20},
            {"x": 24, "y": 15, "frameIndex": 0, "frameTime": 46},
        ],
    }
    supported_bridge_candidates, supported_bridge_analysis = generate_candidates(
        supported_bridge_snapshot, []
    )
    assert_true(
        supported_bridge_analysis["movement"]["details"]["left"]["openHole"][
            "occupiedByTrappedGuard"
        ],
        "supported bridge fixture marks the pressure-side hole as occupied",
    )
    assert_true(
        "wait_for_trap_resolution"
        not in {candidate["kind"] for candidate in supported_bridge_candidates},
        "occupied hole is not treated as separating another approaching guard",
    )
    assert_true(
        any(
            candidate["firstAction"]["keyCode"] == 39
            for candidate in supported_bridge_candidates
        ),
        "runner can retreat across the opposite guard-supported hole",
    )

    far_trap_snapshot = {
        **separated_trap_snapshot,
        "guards": [
            {"id": 1, "x": 24, "y": 13, "xOffset": 0, "yOffset": 0, "actionName": "in_hole"},
            {"id": 2, "x": 14, "y": 12, "xOffset": 0, "yOffset": 0, "actionName": "right"},
        ],
    }
    far_trap_candidates, _far_trap_analysis = generate_candidates(far_trap_snapshot, [])
    far_wait = next(
        candidate
        for candidate in far_trap_candidates
        if candidate["kind"] == "wait_for_trap_resolution"
    )
    assert_equal(
        far_wait["firstAction"]["ticks"],
        8,
        "far trap polling advances eight ticks to conserve decision budget",
    )

    upper_gold_route_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 14, "y": 9, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "guards": [],
        "gold": {
            "complete": False,
            "remainingCount": 1,
            "visiblePositions": [{"x": 23, "y": 3}],
            "carriedByGuards": [],
        },
        "goldCount": 1,
    }
    upper_route_candidates, _upper_route_analysis = generate_candidates(
        upper_gold_route_snapshot, []
    )
    upper_route = next(
        candidate
        for candidate in upper_route_candidates
        if candidate["kind"] == "classic_gold_route"
    )
    assert_equal(
        upper_route["target"]["x"],
        20,
        "row-nine upper-gold routing commits to the x=20 ladder",
    )
    assert_equal(
        upper_route["firstAction"]["keyCode"],
        39,
        "upper-gold waypoint moves right from the left network",
    )

    post_top_gold_snapshot = {
        **upper_gold_route_snapshot,
        "runner": {"x": 4, "y": 1, "xOffset": -8, "yOffset": 0, "actionName": "stop"},
    }
    post_top_gold_candidates, _post_top_gold_analysis = generate_candidates(
        post_top_gold_snapshot, []
    )
    post_top_gold_route = next(
        candidate
        for candidate in post_top_gold_candidates
        if candidate["kind"] == "classic_gold_route"
    )
    assert_equal(
        post_top_gold_route["target"]["x"],
        7,
        "post-top-gold routing returns to the row-one descent entry",
    )
    assert_equal(
        post_top_gold_route["firstAction"]["keyCode"],
        39,
        "post-top-gold routing moves right instead of waiting",
    )
    assert_true(
        "wait_or_stop" not in {candidate["kind"] for candidate in post_top_gold_candidates},
        "post-top-gold state has a progress candidate",
    )

    carried_only_row_one_snapshot = {
        **post_top_gold_snapshot,
        "gold": {
            "complete": False,
            "remainingCount": 1,
            "visiblePositions": [],
            "carriedByGuards": [{"id": 1, "x": 7, "y": 5, "hasGold": 14}],
        },
        "goldCount": 1,
        "guards": [
            {"id": 1, "x": 7, "y": 5, "xOffset": 0, "yOffset": 0, "actionName": "down", "hasGold": 14}
        ],
    }
    carried_row_one_candidates, carried_row_one_analysis = generate_candidates(
        carried_only_row_one_snapshot, []
    )
    carried_row_one_route = next(
        candidate
        for candidate in carried_row_one_candidates
        if candidate["kind"] == "classic_gold_route"
    )
    assert_true(
        carried_row_one_analysis["primaryProgressTarget"] is None,
        "guard-carried gold remains excluded from unsafe direct targeting",
    )
    assert_equal(
        carried_row_one_route["target"]["x"],
        7,
        "carried-only row-one state returns to the descent entry",
    )
    assert_equal(
        carried_row_one_route["firstAction"]["keyCode"],
        39,
        "carried-only recovery moves right instead of falling back to repeated stops",
    )
    assert_true(
        "wait_or_stop"
        not in {candidate["kind"] for candidate in carried_row_one_candidates},
        "carried-only row-one state has no generic wait",
    )

    carried_entry_snapshot = {
        **carried_only_row_one_snapshot,
        "godMode": True,
        "runner": {"x": 7, "y": 1, "xOffset": 0, "yOffset": 18, "actionName": "stop"},
        "guards": [
            {
                "id": 1,
                "x": 7,
                "y": 1,
                "xOffset": 0,
                "yOffset": 7,
                "actionName": "left",
                "hasGold": 4,
            }
        ],
        "gold": {
            "complete": False,
            "remainingCount": 1,
            "visiblePositions": [],
            "carriedByGuards": [{"id": 1, "x": 7, "y": 1, "hasGold": 4}],
        },
    }
    carried_entry_candidates, carried_entry_analysis = generate_candidates(
        carried_entry_snapshot, []
    )
    carried_entry_route = next(
        candidate
        for candidate in carried_entry_candidates
        if candidate["id"] == "classic_gold_route_7_2_down"
    )
    assert_equal(
        carried_entry_route["firstAction"]["keyCode"],
        40,
        "carried-only recovery descends from the row-one x=7 entry",
    )
    assert_equal(
        carried_entry_route["firstAction"]["ticks"],
        4,
        "carried-only descent uses a short reassessed ladder entry",
    )
    assert_true(
        "wait_or_stop" not in {candidate["kind"] for candidate in carried_entry_candidates},
        "trace-shaped carried-only entry cannot fall back to waiting",
    )
    assert_true(
        "same-row gold is available"
        not in carried_entry_analysis["routeAccess"]["reason"],
        "guard-carried gold does not block structural route access as collectible gold",
    )

    carried_ladder_snapshot = {
        **carried_entry_snapshot,
        "runner": {"x": 7, "y": 2, "xOffset": 0, "yOffset": 0, "actionName": "down"},
        "guards": [
            {
                "id": 1,
                "x": 7,
                "y": 3,
                "xOffset": 0,
                "yOffset": -18,
                "actionName": "down",
                "hasGold": 4,
            }
        ],
        "gold": {
            "complete": False,
            "remainingCount": 1,
            "visiblePositions": [],
            "carriedByGuards": [{"id": 1, "x": 7, "y": 3, "hasGold": 4}],
        },
    }
    carried_ladder_candidates, _carried_ladder_analysis = generate_candidates(
        carried_ladder_snapshot, []
    )
    carried_ladder_climb = next(
        candidate
        for candidate in carried_ladder_candidates
        if candidate["kind"] == "climb_ladder"
    )
    assert_equal(
        carried_ladder_climb["firstAction"]["keyCode"],
        40,
        "carried-only ladder recovery continues down instead of reversing upward",
    )
    assert_true(
        all(candidate["kind"] != "descend_route" for candidate in carried_ladder_candidates),
        "guard carrier is excluded from ordinary descent targeting",
    )

    dropped_entry_snapshot = {
        **carried_entry_snapshot,
        "guards": [
            {
                "id": 1,
                "x": 7,
                "y": 1,
                "xOffset": 0,
                "yOffset": 0,
                "actionName": "right",
                "hasGold": -1,
            }
        ],
        "gold": {
            "complete": False,
            "remainingCount": 1,
            "visiblePositions": [{"x": 7, "y": 1}],
            "carriedByGuards": [],
        },
    }
    dropped_entry_candidates, dropped_entry_analysis = generate_candidates(
        dropped_entry_snapshot, []
    )
    dropped_entry_collect = next(
        candidate
        for candidate in dropped_entry_candidates
        if candidate["id"] == "collect_current_tile_gold_7_1_up"
    )
    assert_true(
        dropped_entry_analysis["movement"]["canFinishLadderClimb"],
        "row-one offset state exposes final ladder alignment",
    )
    assert_equal(
        dropped_entry_collect["firstAction"]["ticks"],
        3,
        "same-tile dropped gold centers vertically instead of issuing repeated stops",
    )

    lower_gold_route_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 14, "y": 6, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "guards": [],
        "gold": {
            "complete": False,
            "remainingCount": 1,
            "visiblePositions": [{"x": 15, "y": 14}],
            "carriedByGuards": [],
        },
        "goldCount": 1,
    }
    lower_route_candidates, _lower_route_analysis = generate_candidates(
        lower_gold_route_snapshot, []
    )
    lower_route = next(
        candidate
        for candidate in lower_route_candidates
        if candidate["kind"] == "classic_gold_route"
    )
    assert_equal(
        lower_route["target"]["x"],
        20,
        "row-six lower-gold routing commits to the below-row x=20 ladder entry",
    )
    assert_equal(
        lower_route["firstAction"]["keyCode"],
        39,
        "lower-gold waypoint moves right from x=14 instead of oscillating at its dead-end ladder",
    )

    left_gold_route_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 2, "y": 9, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "guards": [],
        "gold": {
            "complete": False,
            "remainingCount": 1,
            "visiblePositions": [{"x": 7, "y": 12}],
            "carriedByGuards": [],
        },
        "goldCount": 1,
    }
    left_route_candidates, _left_route_analysis = generate_candidates(
        left_gold_route_snapshot, []
    )
    left_route = next(
        candidate
        for candidate in left_route_candidates
        if candidate["kind"] == "classic_gold_route"
    )
    assert_equal(
        left_route["target"]["x"],
        20,
        "row-nine routing for gold at (7,12) commits to the x=20 descent ladder",
    )
    assert_equal(
        left_route["firstAction"]["keyCode"],
        39,
        "left-side lower-gold waypoint leaves the dead-end x=2 ladder to the right",
    )

    bottom_left_route_snapshot = {
        **left_gold_route_snapshot,
        "runner": {"x": 11, "y": 14, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "guards": [
            {
                "id": 2,
                "x": 9,
                "y": 11,
                "xOffset": 0,
                "yOffset": 17,
                "actionName": "down",
            }
        ],
    }
    bottom_left_candidates, bottom_left_analysis = generate_candidates(
        bottom_left_route_snapshot, []
    )
    bottom_left_route = next(
        candidate
        for candidate in bottom_left_candidates
        if candidate["kind"] == "classic_gold_route"
    )
    assert_equal(
        bottom_left_route["target"]["x"],
        27,
        "row-fourteen routing for gold at (7,12) uses the viable right-edge ladder",
    )
    assert_equal(
        bottom_left_route["firstAction"]["keyCode"],
        39,
        "bottom left-gold route agrees with retreat away from the left-side guard",
    )
    assert_equal(
        bottom_left_analysis["risk"]["risk"],
        "medium",
        "bottom route regression preserves the trace guard-pressure class",
    )
    assert_true(
        "align_ladder_4_14_left"
        not in {candidate["id"] for candidate in bottom_left_candidates},
        "explicit Classic routing removes the conflicting dead-end ladder alternative",
    )

    exit_offset_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 18, "y": 0, "xOffset": 0, "yOffset": 6, "actionName": "stop"},
        "guards": [],
        "gold": {
            "complete": True,
            "remainingCount": 0,
            "visiblePositions": [],
            "carriedByGuards": [],
        },
        "goldComplete": True,
        "goldCount": 0,
    }
    exit_offset_candidates, exit_offset_analysis = generate_candidates(exit_offset_snapshot, [])
    finish_exit = next(
        candidate for candidate in exit_offset_candidates if candidate["kind"] == "exit_ladder_route"
    )
    assert_true(
        exit_offset_analysis["movement"]["canFinishExitClimb"],
        "positive top-row exit offset is a valid final climb state",
    )
    assert_equal(finish_exit["firstAction"]["keyCode"], 38, "final exit offset continues upward")

    medium_spacing_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 25, "y": 12, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "guards": [{"id": 0, "x": 20, "y": 12, "actionName": "right"}],
    }
    medium_spacing_candidates, _medium_spacing_analysis = generate_candidates(
        medium_spacing_snapshot, []
    )
    assert_true(
        "defensive_dig" not in {candidate["kind"] for candidate in medium_spacing_candidates},
        "medium guard outside trap geometry does not create another defensive hole",
    )

    edge_medium_trap_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 27, "y": 12, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "guards": [
            {"id": 1, "x": 22, "y": 12, "xOffset": -8, "yOffset": 0, "actionName": "right"},
        ],
    }
    edge_medium_candidates, edge_medium_analysis = generate_candidates(
        edge_medium_trap_snapshot, []
    )
    assert_true(
        edge_medium_analysis["risk"]["runnerOnEdge"],
        "edge trap fixture places the runner at the right boundary",
    )
    assert_true(
        "defensive_dig_dig_left"
        in {candidate["id"] for candidate in edge_medium_candidates},
        "centered edge runner can trap a closing guard at distance five before retreat becomes off-center",
    )
    assert_true(
        "retreat_from_guard_down"
        not in {candidate["id"] for candidate in edge_medium_candidates},
        "edge defense suppresses the ladder descent that immediately routes back into the same pressure state",
    )
    edge_trap = next(
        candidate
        for candidate in edge_medium_candidates
        if candidate["id"] == "defensive_dig_dig_left"
    )
    assert_true(edge_trap["score"] > 118, "edge trap decisively outranks generic vertical retreat")

    bottom_dig_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 27, "y": 14, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "guards": [{"id": 0, "x": 25, "y": 14, "actionName": "right"}],
    }
    bottom_candidates, bottom_analysis = generate_candidates(bottom_dig_snapshot, [])
    assert_true(not bottom_analysis["dig"]["canDigLeft"], "bottom terrain row is not diggable")
    assert_equal(
        bottom_analysis["dig"]["left"]["reason"],
        "bottom terrain row would create an inescapable drop",
        "bottom dig rejection explains the irreversible trap",
    )
    assert_true(
        "defensive_dig" in {candidate["kind"] for candidate in bottom_candidates},
        "bottom-boundary digging remains available only as a guard trap",
    )

    pinch_snapshot = {
        **bottom_dig_snapshot,
        "runner": {"x": 15, "y": 14, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "guards": [
            {"id": 0, "x": 12, "y": 14, "xOffset": -8, "yOffset": 0, "actionName": "right"},
            {"id": 2, "x": 19, "y": 14, "xOffset": 16, "yOffset": 0, "actionName": "left"},
        ],
    }
    pinch_candidates, pinch_analysis = generate_candidates(pinch_snapshot, [])
    pinch_dig = next(
        candidate for candidate in pinch_candidates if candidate["kind"] == "defensive_dig"
    )
    assert_true(
        not is_action_guard_safe({"keyCode": 37}, pinch_analysis),
        "pinch safety blocks movement toward the left guard",
    )
    assert_true(
        not is_action_guard_safe({"keyCode": 39}, pinch_analysis),
        "pinch safety blocks movement toward the right guard",
    )
    assert_equal(pinch_dig["score"], 134, "pinch trap outranks oscillating ladder alignment")

    converging_pinch_snapshot = {
        **bottom_dig_snapshot,
        "runner": {"x": 23, "y": 14, "xOffset": 0, "yOffset": 0, "actionName": "left"},
        "guards": [
            {"id": 1, "x": 26, "y": 14, "xOffset": 8, "yOffset": 0, "actionName": "left"},
            {"id": 0, "x": 16, "y": 14, "xOffset": 16, "yOffset": 0, "actionName": "right"},
        ],
    }
    converging_candidates, converging_analysis = generate_candidates(
        converging_pinch_snapshot, []
    )
    assert_equal(
        converging_analysis["risk"]["pressureGuard"]["id"],
        1,
        "near right guard remains the primary high-risk pressure guard",
    )
    assert_true(
        "defensive_dig_dig_right"
        in {candidate["id"] for candidate in converging_candidates},
        "centered runner retains the trap against the primary closing guard",
    )
    assert_true(
        all(
            candidate["firstAction"]["keyCode"] != 37
            for candidate in converging_candidates
        ),
        "high-pressure escape cannot move toward an opposite closing guard within seven tiles",
    )

    bottom_exit_snapshot = {
        **bottom_dig_snapshot,
        "runner": {"x": 13, "y": 14, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "guards": [],
        "gold": {"complete": True, "remainingCount": 0, "visiblePositions": []},
        "goldComplete": True,
        "goldCount": 0,
    }
    bottom_exit_candidates, _bottom_exit_analysis = generate_candidates(bottom_exit_snapshot, [])
    bottom_exit_route = next(
        candidate
        for candidate in bottom_exit_candidates
        if candidate["id"] == "exit_ladder_route_27_14_right"
    )
    assert_equal(bottom_exit_route["kind"], "exit_ladder_route", "bottom exit waypoint kind")
    assert_equal(bottom_exit_route["firstAction"]["keyCode"], 39, "bottom exit waypoint moves right")
    assert_equal(
        bottom_exit_route["firstAction"]["ticks"],
        20,
        "deterministic exit macros use the full legacy action window",
    )

    near_exit_snapshot = {
        **bottom_exit_snapshot,
        "runner": {"x": 17, "y": 12, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
    }
    near_exit_candidates, _near_exit_analysis = generate_candidates(near_exit_snapshot, [])
    near_exit_route = next(
        candidate
        for candidate in near_exit_candidates
        if candidate["id"] == "exit_ladder_route_20_12_right"
    )
    assert_equal(
        near_exit_route["firstAction"]["ticks"],
        12,
        "nearby exit waypoints shorten horizontal macros to avoid overshoot",
    )
    assert_true(
        bottom_exit_route["score"] > max(
            candidate["score"]
            for candidate in bottom_exit_candidates
            if candidate["kind"] == "align_ladder"
        ),
        "directed bottom exit route outranks generic ladder alignment",
    )

    top_exit_snapshot = {
        **bottom_exit_snapshot,
        "runner": {"x": 14, "y": 1, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
    }
    top_exit_candidates, _top_exit_analysis = generate_candidates(top_exit_snapshot, [])
    top_exit_route = next(
        candidate
        for candidate in top_exit_candidates
        if candidate["id"] == "exit_ladder_route_18_1_right"
    )
    assert_true(top_exit_route["score"] >= 125, "top gap crossing is explicit exit routing")
    assert_equal(top_exit_route["firstAction"]["keyCode"], 39, "top exit waypoint moves right")

    rope_exit_snapshot = {
        **bottom_exit_snapshot,
        "runner": {"x": 15, "y": 3, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
    }
    rope_exit_candidates, _rope_exit_analysis = generate_candidates(rope_exit_snapshot, [])
    assert_true(
        "exit_ladder_route_18_3_right"
        in {candidate["id"] for candidate in rope_exit_candidates},
        "row-3 rope traversal explicitly targets the revealed exit ladder",
    )

    boxed_grid = [" " * 28 for _ in range(16)]
    boxed_row = list(boxed_grid[12])
    boxed_row[21] = "#"
    boxed_row[23] = "#"
    boxed_grid[12] = "".join(boxed_row)
    boxed_floor = list(boxed_grid[13])
    boxed_floor[22] = "#"
    boxed_grid[13] = "".join(boxed_floor)
    boxed_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 22, "y": 12, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "guards": [
            {
                "id": 2,
                "x": 22,
                "y": 14,
                "xOffset": -8,
                "yOffset": 0,
                "actionName": "right",
            }
        ],
        "gold": {
            "complete": False,
            "remainingCount": 1,
            "visiblePositions": [{"x": 4, "y": 1}],
            "carriedByGuards": [],
        },
        "goldCount": 1,
        "terrainGrid": boxed_grid,
    }
    boxed_candidates, boxed_analysis = generate_candidates(boxed_snapshot, [])
    assert_equal(boxed_analysis["risk"]["risk"], "high", "boxed fixture has cross-row pressure")
    assert_equal(
        [candidate["kind"] for candidate in boxed_candidates],
        ["emergency_hold"],
        "separated-row pressure never produces an empty candidate set",
    )
    boxed_selected, boxed_validation = validate_or_fallback_candidate(
        {
            "choice": {
                "candidateId": boxed_candidates[0]["id"],
                "reason": "only safe generated action",
            }
        },
        boxed_candidates,
        boxed_analysis,
    )
    assert_equal(
        boxed_selected["kind"],
        "emergency_hold",
        "validator preserves the generated emergency candidate",
    )
    assert_true(not boxed_validation["fallbackUsed"], "validator accepts the generated hold")

    cross_row_wait_history = movement_history(
        [boxed_candidates[0]["id"]] * 6,
        [(22, 12)] * 6,
        [32] * 6,
    )
    _boxed_wait_candidates, boxed_wait_analysis = generate_candidates(
        boxed_snapshot, cross_row_wait_history
    )
    assert_true(
        not boxed_wait_analysis["loopReport"]["active"],
        "guard-signature cross-row holds are environment progress",
    )

    aligned_grid = terrain.copy()
    aligned_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 7, "y": 1, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "guards": [
            {"id": 0, "x": 7, "y": 4, "xOffset": 0, "yOffset": -20, "actionName": "up"}
        ],
        "gold": {
            "complete": False,
            "remainingCount": 2,
            "visiblePositions": [{"x": 23, "y": 3}],
            "carriedByGuards": [{"id": 0, "x": 7, "y": 4, "hasGold": 3}],
        },
        "goldCount": 2,
        "terrainGrid": aligned_grid,
    }
    aligned_candidates, aligned_analysis = generate_candidates(aligned_snapshot, [])
    aligned_ids = {candidate["id"] for candidate in aligned_candidates}
    assert_equal(
        aligned_analysis["risk"]["pressureGuard"]["relativeX"],
        "same",
        "aligned fixture keeps guard on runner column",
    )
    assert_true(
        {
            "retreat_from_guard_same_column_left",
            "retreat_from_guard_same_column_right",
        }.issubset(aligned_ids),
        "same-column cross-row pressure exposes both legal horizontal escapes",
    )
    assert_true(
        "emergency_hold" not in {candidate["kind"] for candidate in aligned_candidates},
        "emergency hold remains reserved for positions without an ordinary escape",
    )

    escape_active_grid = terrain.copy()
    escape_floor = list(escape_active_grid[13])
    escape_floor[26] = " "
    escape_active_grid[13] = "".join(escape_floor)
    climb_out_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 27, "y": 12, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "guards": [
            {"id": 1, "x": 26, "y": 12, "xOffset": 0, "yOffset": 17, "actionName": "climb_out"},
        ],
        "grid": escape_active_grid,
        "openHoles": [{"x": 26, "y": 13, "frameIndex": 0, "frameTime": 114}],
    }
    climb_out_candidates, _climb_out_analysis = generate_candidates(
        climb_out_snapshot, []
    )
    climb_out_kinds = {candidate["kind"] for candidate in climb_out_candidates}
    assert_true(
        "wait_for_trap_resolution" not in climb_out_kinds,
        "guard climbing out beside the runner no longer counts as separating trap geometry",
    )
    climb_out_escape = next(
        candidate
        for candidate in climb_out_candidates
        if candidate["id"] == "retreat_from_guard_down"
    )
    assert_equal(
        climb_out_escape["firstAction"]["keyCode"],
        40,
        "edge runner descends before the adjacent guard completes climb-out",
    )

    lower_climb_out_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 27, "y": 13, "xOffset": 0, "yOffset": 10, "actionName": "down"},
        "guards": [
            {"id": 1, "x": 26, "y": 13, "xOffset": 0, "yOffset": -18, "actionName": "climb_out"},
        ],
    }
    lower_climb_out_candidates, lower_climb_out_analysis = generate_candidates(
        lower_climb_out_snapshot, []
    )
    lower_climb_out_actions = {
        candidate["firstAction"]["keyCode"] for candidate in lower_climb_out_candidates
    }
    assert_equal(
        lower_climb_out_analysis["risk"]["risk"],
        "critical",
        "lower climb-out regression preserves the live failure's pressure class",
    )
    assert_true(
        40 in lower_climb_out_actions,
        "runner may continue down the edge ladder away from a climbing guard",
    )
    assert_true(
        38 not in lower_climb_out_actions,
        "runner is not offered an upward reversal into a climbing guard's escape lane",
    )

    adjacent_hole_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 27, "y": 12, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "guards": [
            {"id": 2, "x": 27, "y": 10, "xOffset": 0, "yOffset": 0, "actionName": "down"}
        ],
        "grid": escape_active_grid,
        "openHoles": [{"x": 26, "y": 13, "frameIndex": 0, "frameTime": 0}],
    }
    adjacent_hole_candidates, adjacent_hole_analysis = generate_candidates(
        adjacent_hole_snapshot, []
    )
    hole_escape = next(
        candidate
        for candidate in adjacent_hole_candidates
        if candidate["kind"] == "escape_through_open_hole"
    )
    assert_equal(
        adjacent_hole_analysis["movement"]["details"]["left"]["openDugHoleDistance"],
        1,
        "escape fixture exposes adjacent left opening",
    )
    assert_equal(hole_escape["firstAction"]["keyCode"], 37, "hole escape moves into opening")
    assert_equal(hole_escape["firstAction"]["ticks"], 4, "hole escape uses a short committed entry")
    assert_true(
        hole_escape["score"] > 110,
        "intentional hole escape outranks ordinary same-column repositioning",
    )

    medium_retreat_drop_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 25, "y": 12, "xOffset": -16, "yOffset": 0, "actionName": "stop"},
        "guards": [
            {"id": 0, "x": 20, "y": 12, "xOffset": 8, "yOffset": 0, "actionName": "right"}
        ],
        "grid": escape_active_grid,
        "openHoles": [{"x": 26, "y": 13, "frameIndex": 1, "frameTime": 4}],
    }
    medium_drop_candidates, medium_drop_analysis = generate_candidates(
        medium_retreat_drop_snapshot, []
    )
    medium_drop = next(
        candidate
        for candidate in medium_drop_candidates
        if candidate["kind"] == "escape_through_open_hole"
    )
    assert_equal(
        medium_drop_analysis["risk"]["risk"],
        "medium",
        "retreat-drop fixture preserves medium same-row pressure",
    )
    assert_equal(
        medium_drop["firstAction"]["keyCode"],
        39,
        "closing medium guard exposes the adjacent hole only on the retreat side",
    )

    bottom_escape_grid = terrain.copy()
    bottom_escape_floor = list(bottom_escape_grid[15])
    bottom_escape_floor[18] = " "
    bottom_escape_grid[15] = "".join(bottom_escape_floor)
    bottom_escape_snapshot = {
        **pinch_snapshot,
        "runner": {"x": 17, "y": 14, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "guards": [
            {"id": 0, "x": 14, "y": 14, "xOffset": 0, "yOffset": 0, "actionName": "right"},
            {"id": 2, "x": 18, "y": 15, "xOffset": 0, "yOffset": 0, "actionName": "in_hole"},
        ],
        "grid": bottom_escape_grid,
        "openHoles": [{"x": 18, "y": 15, "frameIndex": 0, "frameTime": 4}],
    }
    bottom_escape_candidates, _bottom_escape_analysis = generate_candidates(
        bottom_escape_snapshot, []
    )
    assert_true(
        "escape_through_open_hole"
        not in {candidate["kind"] for candidate in bottom_escape_candidates},
        "emergency escape never enters a bottom-boundary hole",
    )

    intercepted_escape_grid = terrain.copy()
    intercepted_floor = list(intercepted_escape_grid[13])
    intercepted_floor[8] = " "
    intercepted_escape_grid[13] = "".join(intercepted_floor)
    intercepted_escape_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 7, "y": 12, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "guards": [
            {"id": 1, "x": 9, "y": 14, "xOffset": 8, "yOffset": 0, "actionName": "left"},
            {"id": 2, "x": 7, "y": 14, "xOffset": -8, "yOffset": 0, "actionName": "left"},
        ],
        "grid": intercepted_escape_grid,
        "openHoles": [{"x": 8, "y": 13, "frameIndex": 0, "frameTime": 4}],
    }
    intercepted_candidates, _intercepted_analysis = generate_candidates(
        intercepted_escape_snapshot, []
    )
    assert_true(
        "escape_through_open_hole"
        not in {candidate["kind"] for candidate in intercepted_candidates},
        "emergency escape is withheld when guards cover both landing sides",
    )

    climbing_intercept_snapshot = {
        **adjacent_hole_snapshot,
        "guards": [
            {"id": 2, "x": 27, "y": 14, "xOffset": -16, "yOffset": 0, "actionName": "up"}
        ],
    }
    climbing_intercept_candidates, _climbing_intercept_analysis = generate_candidates(
        climbing_intercept_snapshot, []
    )
    assert_true(
        "escape_through_open_hole"
        not in {candidate["kind"] for candidate in climbing_intercept_candidates},
        "emergency escape rejects an adjacent landing-row guard climbing into the lane",
    )

    hole_row_intercept_snapshot = {
        **adjacent_hole_snapshot,
        "guards": [
            {"id": 2, "x": 27, "y": 13, "xOffset": 0, "yOffset": 17, "actionName": "up"}
        ],
    }
    hole_row_intercept_candidates, _hole_row_intercept_analysis = generate_candidates(
        hole_row_intercept_snapshot, []
    )
    assert_true(
        "escape_through_open_hole"
        not in {candidate["kind"] for candidate in hole_row_intercept_candidates},
        "emergency escape rejects a guard adjacent on the open-hole row",
    )

    crossing_intercept_snapshot = {
        **adjacent_hole_snapshot,
        "guards": [
            {"id": 2, "x": 27, "y": 14, "xOffset": -8, "yOffset": 0, "actionName": "right"}
        ],
    }
    crossing_intercept_candidates, _crossing_intercept_analysis = generate_candidates(
        crossing_intercept_snapshot, []
    )
    assert_true(
        "escape_through_open_hole"
        not in {candidate["kind"] for candidate in crossing_intercept_candidates},
        "emergency escape rejects an adjacent landing-row guard crossing the lane",
    )

    trapped_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 27, "y": 12, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "guards": [
            {"id": 1, "x": 24, "y": 13, "xOffset": 0, "yOffset": 0, "actionName": "in_hole"},
            {"id": 2, "x": 15, "y": 12, "xOffset": 8, "yOffset": 0, "actionName": "right"},
        ],
        "gold": {
            "complete": False,
            "remainingCount": 4,
            "visiblePositions": [{"x": 24, "y": 12}],
            "carriedByGuards": [],
        },
    }
    trapped_candidates, trapped_analysis = generate_candidates(trapped_snapshot, [])
    assert_equal(trapped_analysis["risk"]["risk"], "low", "contained guard does not force retreat")
    assert_true(
        "collect_same_row_gold_24_12_left"
        in {candidate["id"] for candidate in trapped_candidates},
        "progress above a contained guard remains available",
    )

    open_floor_grid = terrain.copy()
    open_floor_row = list(open_floor_grid[13])
    open_floor_row[24] = " "
    open_floor_grid[13] = "".join(open_floor_row)
    open_floor_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 25, "y": 12, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "guards": [],
        "gold": {
            "complete": False,
            "remainingCount": 1,
            "visiblePositions": [{"x": 23, "y": 12}],
            "carriedByGuards": [],
        },
        "grid": open_floor_grid,
        "openHoles": [{"x": 24, "y": 13, "frameIndex": 0, "frameTime": 40}],
    }
    open_floor_candidates, open_floor_analysis = generate_candidates(open_floor_snapshot, [])
    assert_true(
        open_floor_analysis["movement"]["details"]["left"]["wouldFallIntoOpenHole"],
        "movement analysis identifies a dug hole below the next tile",
    )
    assert_true(
        "collect_same_row_gold_23_12_left"
        not in {candidate["id"] for candidate in open_floor_candidates},
        "ordinary gold progress does not enter an open dug hole",
    )
    assert_true(
        "wait_or_stop" not in {candidate["id"] for candidate in open_floor_candidates},
        "generic waiting does not compete with a timed floor-refill candidate",
    )
    refill = next(
        candidate
        for candidate in open_floor_candidates
        if candidate["kind"] == "wait_for_floor_refill"
    )
    assert_equal(refill["firstAction"]["ticks"], 8, "floor refill wait advances eight ticks")
    assert_true(
        "0_40" in refill["id"],
        "floor refill wait identity tracks legacy refill progress",
    )

    exit_open_floor_grid = terrain.copy()
    exit_floor_row = list(exit_open_floor_grid[7])
    exit_floor_row[5] = " "
    exit_open_floor_grid[7] = "".join(exit_floor_row)
    exit_open_floor_snapshot = {
        **pressure_snapshot,
        "runner": {"x": 4, "y": 6, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "guards": [],
        "gold": {
            "complete": True,
            "remainingCount": 0,
            "visiblePositions": [],
            "carriedByGuards": [],
        },
        "goldComplete": True,
        "goldCount": 0,
        "grid": exit_open_floor_grid,
        "openHoles": [{"x": 5, "y": 7, "frameIndex": 0, "frameTime": 0}],
    }
    exit_loop_history = movement_history(
        ["exit_ladder_route_25_6_right", "retreat_from_guard_left"] * 3,
        [(4, 6), (5, 6), (4, 6), (5, 6), (4, 6), (5, 6)],
        [39, 37] * 3,
    )
    exit_open_floor_candidates, exit_open_floor_analysis = generate_candidates(
        exit_open_floor_snapshot, exit_loop_history
    )
    exit_refill = next(
        candidate
        for candidate in exit_open_floor_candidates
        if candidate["kind"] == "wait_for_floor_refill"
    )
    assert_true(
        exit_refill["id"] not in {
            item["id"]
            for item in exit_open_floor_analysis["loopReport"]["suppressedCandidates"]
        },
        "exit routing can wait for a required dug brick during a confirmed cycle",
    )
    assert_true(
        "exit progress" in exit_refill["firstAction"]["reason"],
        "exit refill reason is explicit",
    )

    approach_floor_grid = terrain.copy()
    approach_floor_row = list(approach_floor_grid[13])
    approach_floor_row[25] = " "
    approach_floor_grid[13] = "".join(approach_floor_row)
    approach_snapshot = {
        **open_floor_snapshot,
        "runner": {"x": 27, "y": 12, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "gold": {
            "complete": False,
            "remainingCount": 1,
            "visiblePositions": [{"x": 24, "y": 12}],
            "carriedByGuards": [],
        },
        "grid": approach_floor_grid,
        "openHoles": [{"x": 25, "y": 13, "frameIndex": 0, "frameTime": 44}],
    }
    approach_candidates, approach_analysis = generate_candidates(approach_snapshot, [])
    approach = next(
        candidate
        for candidate in approach_candidates
        if candidate["id"] == "collect_same_row_gold_24_12_left"
    )
    assert_equal(
        approach_analysis["movement"]["details"]["left"]["openDugHoleDistance"],
        2,
        "movement analysis looks ahead to a dug hole two tiles away",
    )
    assert_equal(
        approach["firstAction"]["ticks"],
        4,
        "horizontal progress stops one tile before an open dug hole",
    )

    current_gold_snapshot = {
        **open_floor_snapshot,
        "runner": {"x": 25, "y": 12, "xOffset": 16, "yOffset": 0, "actionName": "stop"},
        "gold": {
            "complete": False,
            "remainingCount": 1,
            "visiblePositions": [{"x": 25, "y": 12}],
            "carriedByGuards": [],
        },
    }
    current_gold_candidates, _current_gold_analysis = generate_candidates(
        current_gold_snapshot, []
    )
    current_gold = next(
        candidate
        for candidate in current_gold_candidates
        if candidate["kind"] == "collect_current_tile_gold"
    )
    assert_equal(current_gold["firstAction"]["keyCode"], 37, "positive offset centers left")
    assert_equal(current_gold["firstAction"]["ticks"], 4, "current-tile centering is bounded")

    opened_grid = terrain.copy()
    opened_row = list(opened_grid[2])
    opened_row[5] = " "
    opened_grid[2] = "".join(opened_row)
    access_snapshot = {
        "playData": 1,
        "level": 1,
        "gameStateName": "running",
        "godMode": False,
        "runner": {"x": 4, "y": 1, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "guards": [
            {"id": 1, "x": 3, "y": 6, "xOffset": -16, "yOffset": 0, "actionName": "right"}
        ],
        "gold": {
            "complete": False,
            "remainingCount": 1,
            "visiblePositions": [{"x": 19, "y": 6}],
            "carriedByGuards": [],
        },
        "goldComplete": False,
        "goldCount": 1,
        "terrainGrid": terrain,
        "grid": opened_grid,
    }
    access_candidates, access_analysis = generate_candidates(access_snapshot, [])
    assert_true(
        access_analysis["routeAccess"]["followBlockedByGuard"],
        "opened drop is blocked while a guard can intercept below",
    )
    access_kinds = {candidate["kind"] for candidate in access_candidates}
    assert_true(
        "route_access_follow" not in access_kinds,
        "unsafe opened drop does not expose a follow candidate",
    )
    assert_true(
        "wait_for_guard_clearance" in access_kinds,
        "unsafe opened drop exposes an explicit guard-clearance wait",
    )

    clear_candidates, clear_analysis = generate_candidates({**access_snapshot, "guards": []}, [])
    assert_true(
        clear_analysis["routeAccess"]["followAvailable"],
        "opened drop becomes available after guards clear",
    )
    assert_true(
        "route_access_follow" in {candidate["kind"] for candidate in clear_candidates},
        "clear opened drop exposes a follow candidate",
    )

    safer_side_snapshot = {
        **access_snapshot,
        "guards": [
            {"id": 0, "x": 2, "y": 9, "xOffset": 0, "yOffset": 0, "actionName": "up"}
        ],
        "gold": {
            "complete": False,
            "remainingCount": 1,
            "visiblePositions": [{"x": 0, "y": 6}],
            "carriedByGuards": [],
        },
        "grid": terrain,
        "openHoles": [],
    }
    safer_candidates, safer_analysis = generate_candidates(safer_side_snapshot, [])
    assert_equal(
        safer_analysis["routeAccess"]["recommendedAction"],
        "dig_right",
        "guard interception risk overrides the gold-facing access dig",
    )
    assert_true(
        "route_access_dig_right" in {candidate["id"] for candidate in safer_candidates},
        "safer opposite-side access dig is emitted",
    )

    both_open_grid = terrain.copy()
    both_open_row = list(both_open_grid[2])
    both_open_row[3] = " "
    both_open_row[5] = " "
    both_open_grid[2] = "".join(both_open_row)
    both_open_snapshot = {
        **safer_side_snapshot,
        "guards": [
            {"id": 0, "x": 2, "y": 6, "xOffset": 0, "yOffset": 0, "actionName": "right"}
        ],
        "grid": both_open_grid,
    }
    both_open_candidates, both_open_analysis = generate_candidates(both_open_snapshot, [])
    assert_equal(
        both_open_analysis["routeAccess"]["followAction"],
        "right",
        "opened access chooses the guard-clear side instead of the preferred unsafe side",
    )
    assert_true(
        "route_access_follow" in {candidate["kind"] for candidate in both_open_candidates},
        "guard-clear opened side remains followable",
    )


def run() -> None:
    check_loop_filter_regressions()
    check_guard_safety_regressions()
    original_store = app_module.STORE_PATH
    original_trace_store = app_module.TRACE_STORE_PATH

    with tempfile.TemporaryDirectory(prefix="runner-sanity-") as tmp:
        tmp_path = Path(tmp)
        app_module.STORE_PATH = tmp_path / "recordings.json"
        app_module.TRACE_STORE_PATH = tmp_path / "agent-traces.json"

        try:
            client = app_module.app.test_client()

            health = client.get("/api/health")
            assert_equal(health.status_code, 200, "health status")
            assert_equal(health.get_json(), {"ok": True}, "health body")

            user_record = put_record(
                client,
                {
                    "id": "user:first",
                    "demo": demo(time=16),
                    "source": "user",
                    "result": "success",
                    "pinned": True,
                },
            )
            assert_equal(user_record["id"], "user:first", "user record id")
            assert_equal(user_record["source"], "user", "user source")
            assert_equal(user_record["result"], "success", "user result")
            assert_equal(user_record["demo"]["time"], 16, "demo time stored")
            assert_equal(user_record["pinned"], False, "new recording starts unpinned")

            store = json.loads(app_module.STORE_PATH.read_text())
            store["records"]["user:first"]["pinned"] = True
            app_module.STORE_PATH.write_text(json.dumps(store))
            user_record = put_record(
                client,
                {
                    "id": "user:first",
                    "demo": demo(time=24),
                    "source": "user",
                    "result": "success",
                    "pinned": False,
                },
            )
            assert_equal(user_record["pinned"], True, "record save preserves pin")
            blocked_user_delete = client.delete(
                "/api/recordings/1/1?recordId=user:first"
            )
            assert_equal(blocked_user_delete.status_code, 409, "pinned delete blocked")
            assert_equal(
                blocked_user_delete.get_json()["pinned"],
                True,
                "pinned delete response",
            )

            put_record(
                client,
                {
                    "id": "user:second",
                    "demo": demo(time=32),
                    "source": "user",
                    "result": "success",
                },
            )
            listed = client.get("/api/recordings/1/1/records")
            assert_equal(listed.status_code, 200, "records list status")
            records = listed.get_json()["records"]
            assert_equal(records[0]["id"], "user:second", "newest record first")

            deleted = client.delete("/api/recordings/1/1?recordId=user:second")
            assert_equal(deleted.status_code, 200, "delete status")
            assert_true(deleted.get_json()["deleted"], "selected record deleted")
            latest = client.get("/api/recordings/1/1").get_json()
            assert_equal(latest["id"], "user:first", "next newest remains")

            expect_bad_request(
                client,
                {"demo": {"level": 1}, "source": "user"},
                "invalid demo returns 400",
            )
            expect_bad_request(
                client,
                {"demo": demo(), "source": "agent", "result": "failure"},
                "agent recording requires traceId",
            )

            write_trace_run("trace-agent")
            trace_store = json.loads(app_module.TRACE_STORE_PATH.read_text())
            assert_equal(trace_store["version"], 3, "trace store uses compact loop schema")
            agent_record = put_record(
                client,
                {
                    "demo": demo(state=0),
                    "source": "agent",
                    "result": "failure",
                    "traceId": "trace-agent",
                    "finalSnapshot": {
                        "tick": 18,
                        "gameState": "runner_dead",
                        "godMode": False,
                        "runner": {"x": 7, "y": 6, "action": "up"},
                        "guards": [{"id": 2, "x": 7, "y": 5, "action": "down"}],
                        "gold": {"remainingCount": 1, "complete": False},
                    },
                    "solver": {
                        "modelProfile": "openai",
                        "provider": "openai",
                        "model": "openai:test",
                        "traceId": "trace-agent",
                        "failureReason": "test failure",
                    },
                },
            )
            assert_equal(agent_record["id"], "trace-agent", "agent id equals traceId")
            assert_equal(agent_record["solver"]["model"], "openai:test", "solver model stored")
            assert_equal(agent_record["pinned"], False, "new agent record starts unpinned")
            trace_response = client.get("/api/agent/traces/trace-agent")
            assert_equal(trace_response.status_code, 200, "trace exists before delete")
            assert_true(
                "pinned" not in trace_response.get_json(),
                "trace does not duplicate recording pin",
            )
            outcome = trace_response.get_json()["outcome"]
            assert_equal(outcome["result"], "failure", "trace outcome result stored")
            assert_equal(outcome["reason"], "test failure", "trace outcome reason stored")
            assert_equal(
                outcome["finalState"]["guards"][0]["y"],
                5,
                "trace terminal guard state stored",
            )
            store = json.loads(app_module.STORE_PATH.read_text())
            store["records"]["trace-agent"]["pinned"] = True
            app_module.STORE_PATH.write_text(json.dumps(store))
            blocked_agent_delete = client.delete(
                "/api/recordings/1/1?traceId=trace-agent"
            )
            assert_equal(
                blocked_agent_delete.status_code,
                409,
                "pinned agent deletion blocked",
            )
            assert_equal(
                client.get("/api/agent/traces/trace-agent").status_code,
                200,
                "pinned linked trace remains",
            )
            store = json.loads(app_module.STORE_PATH.read_text())
            store["records"]["trace-agent"]["pinned"] = False
            app_module.STORE_PATH.write_text(json.dumps(store))
            deleted_agent = client.delete("/api/recordings/1/1?traceId=trace-agent")
            assert_true(deleted_agent.get_json()["traceDeleted"], "linked trace deleted")
            missing_trace = client.get("/api/agent/traces/trace-agent")
            assert_equal(missing_trace.status_code, 404, "trace deleted")

            pre_step_record = put_record(
                client,
                {
                    "demo": demo(state=0),
                    "source": "agent",
                    "result": "failure",
                    "traceId": "trace-pre-step",
                    "finalSnapshot": {"gameState": "running", "godMode": False},
                    "solver": {
                        "modelProfile": "minimax",
                        "provider": "minimax",
                        "model": "minimax:test",
                        "traceId": "trace-pre-step",
                        "failureReason": "provider unavailable",
                    },
                },
            )
            assert_equal(pre_step_record["id"], "trace-pre-step", "pre-step failure saved")
            pre_step_trace = client.get("/api/agent/traces/trace-pre-step").get_json()
            assert_equal(pre_step_trace["stepCount"], 0, "pre-step trace has no planner steps")
            assert_equal(
                pre_step_trace["outcome"]["reason"],
                "provider unavailable",
                "pre-step trace preserves provider failure",
            )
            assert_equal(
                pre_step_trace["model"]["model"],
                "minimax:test",
                "pre-step trace preserves requested model",
            )

            for index in range(12):
                put_record(
                    client,
                    {
                        "id": f"user:retained-{index:02d}",
                        "demo": demo(time=48 + index),
                        "source": "user",
                        "result": "success",
                    },
                )
            store = json.loads(app_module.STORE_PATH.read_text())
            pinned_records = [
                record
                for record in store["records"].values()
                if record.get("pinned") is True
            ]
            unpinned_records = [
                record
                for record in store["records"].values()
                if record.get("pinned") is not True
            ]
            assert_equal(len(pinned_records), 1, "pinned recording retained")
            assert_equal(pinned_records[0]["id"], "user:first", "old pin survives")
            assert_equal(len(unpinned_records), 10, "recording rolling retention limit")
            assert_equal(len(store["records"]), 11, "pin is outside rolling limit")

            trace_store = {
                "runs": {
                    f"trace-{index:02d}": {
                        "updatedAt": f"2026-01-01T00:00:{index:02d}.000Z",
                    }
                    for index in range(12)
                }
            }
            pinned_trace_ids = app_module.pinned_trace_ids_from_store(
                {
                    "records": {
                        "trace-00": {
                            "pinned": True,
                            "source": "agent",
                            "traceId": "trace-00",
                        },
                        "user:pinned": {
                            "pinned": True,
                            "source": "user",
                            "traceId": "trace-01",
                        },
                        "missing-trace": {
                            "pinned": True,
                            "source": "agent",
                            "traceId": "trace-missing",
                        },
                    }
                }
            )
            assert_equal(
                pinned_trace_ids,
                {"trace-00", "trace-missing"},
                "only pinned agent recordings contribute trace ids",
            )
            app_module.prune_trace_runs(trace_store, pinned_trace_ids)
            assert_equal(len(trace_store["runs"]), 11, "trace pin is outside rolling limit")
            assert_true("trace-11" in trace_store["runs"], "newest trace retained")
            assert_true("trace-00" in trace_store["runs"], "oldest pinned trace retained")
            assert_true("trace-01" not in trace_store["runs"], "oldest unpinned trace pruned")
            assert_true(
                "trace-missing" not in trace_store["runs"],
                "missing pinned trace is not recreated",
            )

            validate_agent_request(
                {
                    "playData": 1,
                    "level": 1,
                    "snapshot": {"playData": 1, "level": 1},
                    "history": [],
                }
            )
            for payload in (
                {"playData": 1, "level": 2, "snapshot": {}, "history": []},
                {"playData": 1, "level": 1, "snapshot": [], "history": []},
                {"playData": 1, "level": 1, "snapshot": {}, "history": {}},
            ):
                try:
                    validate_agent_request(payload)
                except AgentRequestError:
                    pass
                else:
                    raise AssertionError(f"payload should be invalid: {payload!r}")

        finally:
            app_module.STORE_PATH = original_store
            app_module.TRACE_STORE_PATH = original_trace_store

    print("backend sanity ok")


if __name__ == "__main__":
    run()
