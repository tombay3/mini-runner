from __future__ import annotations

import json
import sys
import tempfile
from copy import deepcopy
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
    post_ascent_departed_ladder,
)
from agent.config import MAX_CANDIDATE_LIMIT  # noqa: E402
from agent.candidates import candidate_lane  # noqa: E402
from agent.loop_tools import (  # noqa: E402
    build_loop_report,
    candidate_kind,
    candidate_suppression_reason,
    predicted_horizontal_return_target,
)
from agent.prompt import build_agent_prompt, build_state_context, read_agent_rules  # noqa: E402
from agent.reasoning_tools import find_row_ladders, get_movement_affordance  # noqa: E402
import app as backend_app  # noqa: E402


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


def check_recording_pin_api() -> None:
    original_store_path = backend_app.STORE_PATH
    original_trace_store_path = backend_app.TRACE_STORE_PATH
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            backend_app.STORE_PATH = root / "recordings.json"
            backend_app.TRACE_STORE_PATH = root / "agent-traces.json"
            backend_app.save_store(
                {
                    "version": 1,
                    "updatedAt": None,
                    "records": {
                        "alpha-111": {
                            "id": "alpha-111",
                            "playData": 1,
                            "level": 1,
                            "source": "agent",
                            "traceId": "alpha-111",
                            "pinned": False,
                        },
                        "alpha-222": {
                            "id": "alpha-222",
                            "playData": 1,
                            "level": 1,
                            "source": "agent",
                            "traceId": "alpha-222",
                            "pinned": False,
                        },
                        "unique-333": {
                            "id": "unique-333",
                            "playData": 1,
                            "level": 1,
                            "source": "agent",
                            "traceId": "unique-333",
                            "pinned": False,
                        },
                    },
                }
            )
            trace_store = {
                "version": 3,
                "updatedAt": None,
                "runs": {"unique-333": {"id": "unique-333", "steps": []}},
            }
            backend_app.save_json_store(backend_app.TRACE_STORE_PATH, trace_store)

            client = backend_app.app.test_client()
            response = client.patch(
                "/api/recordings/1/1/pin",
                json={"recordId": "unique", "pinned": True},
            )
            assert_equal(response.status_code, 200, "unique prefix pins a recording")
            assert_equal(response.get_json()["recordId"], "unique-333", "API returns full id")
            assert_true(
                backend_app.load_store()["records"]["unique-333"]["pinned"],
                "pin is persisted",
            )

            response = client.patch(
                "/api/recordings/1/1/pin",
                json={"recordId": "unique-333", "pinned": False},
            )
            assert_equal(response.status_code, 200, "full id unpins a recording")
            assert_true(
                not backend_app.load_store()["records"]["unique-333"]["pinned"],
                "unpin is persisted",
            )
            assert_equal(
                json.loads(backend_app.TRACE_STORE_PATH.read_text(encoding="utf-8")),
                trace_store,
                "pin changes do not modify linked traces",
            )

            assert_equal(
                client.patch(
                    "/api/recordings/1/1/pin",
                    json={"recordId": "alpha-", "pinned": True},
                ).status_code,
                409,
                "ambiguous prefixes are rejected",
            )
            assert_equal(
                client.patch(
                    "/api/recordings/1/1/pin",
                    json={"recordId": "missing", "pinned": True},
                ).status_code,
                404,
                "unknown ids are rejected",
            )
            assert_equal(
                client.patch(
                    "/api/recordings/1/1/pin",
                    json={"recordId": "unique", "pinned": "yes"},
                ).status_code,
                400,
                "pin state must be boolean",
            )
            assert_equal(
                client.patch(
                    "/api/recordings/1/2/pin",
                    json={"recordId": "unique", "pinned": True},
                ).status_code,
                404,
                "prefix resolution stays within the requested context",
            )
    finally:
        backend_app.STORE_PATH = original_store_path
        backend_app.TRACE_STORE_PATH = original_trace_store_path


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

    guarded_state = snapshot(
        grid=["       ", "       ", "#######"],
        runner={"x": 3, "y": 1, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
    )
    guarded_state["guards"] = [
        {
            "id": 1,
            "x": 1,
            "y": 1,
            "xOffset": 0,
            "yOffset": 0,
            "actionName": "right",
        }
    ]
    guarded_analysis = analyze_state(guarded_state, [])
    guarded_builder = CandidateBuilder(
        snapshot=guarded_state,
        analysis=guarded_analysis,
        max_action_ticks=20,
        limit=7,
    )
    guarded_builder.add(
        kind="retreat_from_guard",
        key_code=37,
        ticks=4,
        score=1,
        reason="exercise candidate-audit safety detail",
    )
    safety_rejections = [
        item
        for item in guarded_analysis["candidateAudit"]
        if item.get("disposition") == "safety_rejection"
    ]
    assert_true(safety_rejections, "guard safety rejects the candidate under test")
    assert_true(
        all(str(item.get("detail") or "").strip() for item in safety_rejections),
        "every candidate-audit safety rejection records a meaningful detail",
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
    for god_mode in (False, True):
        for target_y, expected_direction in ((1, "up"), (3, "down"), (None, "up")):
            state = snapshot(
                grid=["       ", "   H   ", "   H   ", "   H   ", "#######"],
                runner={"x": 3, "y": 2, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
            )
            state["godMode"] = god_mode
            state["gold"]["visiblePositions"] = (
                [] if target_y is None else [{"x": 3, "y": target_y}]
            )
            candidates, analysis = generate_candidates(state, [])
            target = analysis.get("primaryProgressTarget")
            if target_y is None:
                assert_true(target is None, "missing visible gold has no invented progress target")
            else:
                assert_equal(target["y"], target_y, "state analysis preserves the computed target")
            assert_equal(
                choose_ladder_direction(state, analysis),
                expected_direction,
                "ladder direction consumes the target from the full analysis path",
            )
            assert_true(
                any(candidate["id"] == f"climb_ladder_3_2_{expected_direction}" for candidate in candidates),
                "target-relative ladder action is exposed",
            )

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


def check_ladder_entry_discovery() -> None:
    for god_mode in (False, True):
        state = snapshot(
            grid=["       ", "H # @  ", " HHHH S", "#######"],
            runner={"x": 1, "y": 1, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        )
        state["godMode"] = god_mode
        state["gold"]["visiblePositions"] = [{"x": 1, "y": 3}]
        ladders = {item["x"]: item for item in find_row_ladders(state)}
        assert_equal(set(ladders), {0, 1, 3}, "discover top entries but exclude blocked and hidden ladders")
        assert_equal(ladders[0]["ladderY"], 1, "ordinary ladder stays on its row")
        assert_true(ladders[0]["entryDirection"] is None, "ordinary ladder is not a top entry")
        assert_equal(ladders[1]["entryDirection"], "down", "top entry has a downward direction")
        assert_equal(ladders[1]["ladderY"], 2, "top entry reports the underlying ladder row")
        assert_equal(ladders[1]["y"], 1, "alignment target remains on the runner row")
        analysis = analyze_state(state, [])
        assert_true(analysis["ladder"]["onDownEntry"], "aligned top entry is identified")
        assert_true(analysis["movement"]["canMoveDown"], "entry matches physical descent affordance")
        context = build_state_context(state, analysis)
        assert_equal(context["route"]["ladder"]["nearest"]["ladderY"], 2, "prompt exposes ladder-entry geometry")
        candidates, _ = generate_candidates(state, [])
        entry_candidate = next(
            (candidate for candidate in candidates if candidate["id"] == "descend_route_1_2_down"),
            None,
        )
        assert_true(entry_candidate is not None, "aligned top entry exposes a downward route candidate")
        assert_equal(entry_candidate["firstAction"]["keyCode"], 40, "entry candidate descends")
        assert_equal(entry_candidate["firstAction"]["ticks"], 6, "entry descent remains bounded")
        assert_equal(entry_candidate["target"]["y"], 2, "entry candidate targets the underlying ladder")
        for target_y, expect_descent, description in (
            (0, False, "an explicitly higher target omits entry descent"),
            (1, False, "a same-row target omits unnecessary entry descent"),
            (3, True, "a lower target retains entry descent"),
            (None, True, "a missing target preserves entry descent"),
        ):
            target_state = deepcopy(state)
            target_state["gold"]["visiblePositions"] = (
                [] if target_y is None else [{"x": 1, "y": target_y}]
            )
            original_state = deepcopy(target_state)
            target_candidates, target_analysis = generate_candidates(target_state, [])
            has_descent = any(
                candidate["id"] == "descend_route_1_2_down"
                for candidate in target_candidates
            )
            assert_equal(has_descent, expect_descent, description)
            assert_equal(
                target_analysis.get("primaryProgressTarget", {}).get("y")
                if target_analysis.get("primaryProgressTarget")
                else None,
                target_y,
                "entry policy consumes the analyzed target row",
            )
            assert_equal(target_state, original_state, "candidate generation preserves its source snapshot")
        if not god_mode:
            guarded_entry = deepcopy(state)
            guarded_entry["gold"]["visiblePositions"] = [{"x": 5, "y": 0}]
            guarded_entry["guards"] = [{
                "id": 884411,
                "x": 1,
                "y": 0,
                "xOffset": 0,
                "yOffset": 0,
                "actionName": "down",
                "hasGold": 0,
            }]
            guarded_candidates, guarded_analysis = generate_candidates(guarded_entry, [])
            assert_true(
                guarded_analysis["risk"]["risk"] in {"high", "critical"},
                "normal fixture activates above-row guard pressure",
            )
            assert_true(
                all(candidate["id"] != "descend_route_1_2_down" for candidate in guarded_candidates),
                "an above target still omits progress descent under guard pressure",
            )
            assert_true(
                any(candidate["id"] == "retreat_from_guard_down" for candidate in guarded_candidates),
                "normal-mode safety descent remains available under an above-row guard",
            )
        climbed_to_entry = [{
            "candidateId": "climb_ladder_1_2_up",
            "keyCode": 38,
            "before": {"runner": {"x": 1, "y": 2}},
            "after": {"runner": {"x": 1, "y": 1}, "goldCount": 2},
        }]
        candidates, _ = generate_candidates(state, climbed_to_entry)
        assert_true(
            all(candidate["id"] != "descend_route_1_2_down" for candidate in candidates),
            "an upward exit does not immediately descend through the same ladder",
        )
        aligned_horizontally = [{
            "candidateId": "align_ladder_1_1_left",
            "keyCode": 37,
            "before": {"runner": {"x": 2, "y": 1}},
            "after": {"runner": {"x": 1, "y": 1}, "goldCount": 2},
        }]
        candidates, _ = generate_candidates(state, aligned_horizontally)
        assert_true(
            any(candidate["id"] == "descend_route_1_2_down" for candidate in candidates),
            "horizontal arrival retains the ladder-entry descent candidate",
        )

        state["runner"]["x"] = 5
        state["terrainGrid"] = state["grid"] = ["       ", "H      ", " HHHH S", "#######"]
        candidates, _ = generate_candidates(state, [])
        assert_true(
            any(candidate["id"] == "align_ladder_3_1_left" for candidate in candidates),
            "discovered top entry is available as an ordinary alignment candidate",
        )
        state["gold"]["complete"] = state["goldComplete"] = True
        assert_true(6 in {item["x"] for item in find_row_ladders(state)}, "revealed exit participates in discovery")
        state["runner"]["y"] = 3
        assert_equal(find_row_ladders(state), [], "bottom map boundary has no invented entry")
        for outside_y in (-1, 4):
            state["runner"]["y"] = outside_y
            assert_equal(find_row_ladders(state), [], "out-of-bounds rows have no ladder routes")

    alignment_grid = ["          ", "        H ", " H      H ", "##########"]
    for god_mode in (False, True):
        for target_y, expected, description in (
            (0, False, "above-row target omits dead-end top-entry alignment"),
            (1, False, "same-row target omits dead-end top-entry alignment"),
            (3, True, "below-row target retains top-entry alignment"),
            (None, True, "missing target retains top-entry alignment"),
        ):
            alignment_state = snapshot(
                grid=alignment_grid,
                runner={"x": 5, "y": 1, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
            )
            alignment_state["godMode"] = god_mode
            alignment_state["gold"]["visiblePositions"] = (
                [] if target_y is None else [{"x": 8, "y": target_y}]
            )
            alignment_candidates, _ = generate_candidates(alignment_state, [])
            alignment_ids = {candidate["id"] for candidate in alignment_candidates}
            assert_equal("align_ladder_1_1_left" in alignment_ids, expected, description)
            assert_true(
                "align_ladder_8_1_right" in alignment_ids,
                "ordinary ladder alignment remains available",
            )


def check_post_ascent_alignment_reversal() -> None:
    state = snapshot(
        grid=["        ", "      H ", " H######", "########"],
        runner={"x": 3, "y": 1, "xOffset": 0, "yOffset": 0, "actionName": "right"},
    )
    state["gold"]["visiblePositions"] = [{"x": 7, "y": 0}]
    climb = {
        "candidateId": "climb_ladder_1_2_up",
        "keyCode": 38,
        "before": {"runner": {"x": 1, "y": 2}, "goldCount": 2},
        "after": {"runner": {"x": 1, "y": 1}, "goldCount": 2},
    }
    depart = {
        "candidateId": "align_ladder_6_1_right",
        "keyCode": 39,
        "before": {"runner": {"x": 1, "y": 1}, "goldCount": 2},
        "after": {"runner": {"x": 3, "y": 1}, "goldCount": 2},
    }

    for god_mode in (False, True):
        state["godMode"] = god_mode
        candidates, _ = generate_candidates(state, [climb, depart])
        candidate_ids = {candidate["id"] for candidate in candidates}
        assert_true(
            "align_ladder_1_1_left" not in candidate_ids,
            "the first decision after a progressing post-ascent departure omits the exited ladder",
        )
        assert_true(
            "align_ladder_6_1_right" in candidate_ids,
            "the progressing alignment target remains available",
        )

        no_progress = deepcopy(depart)
        no_progress["after"] = {"runner": {"x": 1, "y": 1}, "goldCount": 2}
        no_progress_state = deepcopy(state)
        no_progress_state["runner"]["x"] = 1
        candidates, analysis = generate_candidates(no_progress_state, [climb, no_progress])
        assert_true(
            any(candidate["id"] == "align_ladder_6_1_right" for candidate in candidates),
            "blocked alignment does not claim progress",
        )
        assert_true(
            post_ascent_departed_ladder(analysis, [climb, no_progress]) is None,
            "blocked alignment does not activate the transition omission",
        )

        missing_target_state = deepcopy(state)
        missing_target_state["terrainGrid"] = missing_target_state["grid"] = [
            "        ", "        ", " H######", "########",
        ]
        missing_target_state["gold"]["visiblePositions"] = []
        candidates, _ = generate_candidates(missing_target_state, [climb, depart])
        assert_true(
            any(candidate["id"] == "align_ladder_1_1_left" for candidate in candidates),
            "a disappeared continuation target preserves the departed ladder",
        )

        changed_gold = deepcopy(depart)
        changed_gold["after"]["goldCount"] = 1
        candidates, _ = generate_candidates(state, [climb, changed_gold])
        assert_true(
            all(candidate["id"] != "align_ladder_1_1_left" for candidate in candidates),
            "known above-row target still omits dead-end top-entry alignment after gold progress",
        )

        continued = {
            "candidateId": "align_ladder_6_1_right",
            "keyCode": 39,
            "before": {"runner": {"x": 3, "y": 1}, "goldCount": 2},
            "after": {"runner": {"x": 4, "y": 1}, "goldCount": 2},
        }
        continued_state = deepcopy(state)
        continued_state["runner"]["x"] = 4
        candidates, _ = generate_candidates(continued_state, [climb, depart, continued])
        assert_true(
            all(candidate["id"] != "align_ladder_1_1_left" for candidate in candidates),
            "the dead-end top-entry rule remains active on later alignment steps",
        )

    guarded = deepcopy(state)
    guarded["godMode"] = False
    guarded["guards"] = [{
        "id": 884411, "x": 4, "y": 1, "xOffset": 0, "yOffset": 0,
        "actionName": "left", "hasGold": 0,
    }]
    candidates, analysis = generate_candidates(guarded, [climb, depart])
    assert_true(analysis["risk"]["risk"] != "low", "fixture activates normal-mode safety")
    assert_true(
        all(candidate["id"] != "align_ladder_1_1_left" for candidate in candidates),
        "normal threat handling also omits the dead-end top-entry alignment",
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

    progressing_history = [
        {
            "candidateId": candidate_id,
            "keyCode": key_code,
            "before": {"runner": {"x": before_x, "y": 9}},
            "after": {"runner": {"x": after_x, "y": 9}, "goldCount": 2},
        }
        for candidate_id, key_code, before_x, after_x in (
            ("align_ladder_9_9_right", 39, 7, 8),
            ("align_ladder_2_9_left", 37, 8, 6),
            ("align_ladder_9_9_right", 39, 6, 8),
            ("align_ladder_2_9_left", 37, 8, 6),
            ("align_ladder_9_9_right", 39, 6, 7),
            ("align_ladder_9_9_right", 39, 7, 8),
        )
    ]
    progressing = build_loop_report(
        {"activeDig": {}, "primaryProgressTarget": {}, "movement": {}},
        progressing_history,
    )
    assert_equal(progressing["type"], "horizontal_cycle", "progress can occur inside a detected cycle")
    assert_true(progressing["evidence"]["targetProgress"], "trace evidence records decreasing target distance")
    assert_true(not progressing["evidence"]["targetReached"], "unfinished route remains distinguishable from arrival")
    assert_true(
        "align_ladder_9_9_right" not in progressing["suppress"]["candidateIds"],
        "horizontal filtering preserves a route that is approaching its unreached target",
    )
    assert_true(
        candidate_suppression_reason(
            {
                "id": "align_ladder_9_9_right",
                "kind": "align_ladder",
                "firstAction": {"keyCode": 39},
            },
            progressing,
        )
        is None,
        "a progressing repeated candidate remains selectable",
    )

    alternating_history = [
        {
            "candidateId": candidate_id,
            "keyCode": key_code,
            "before": {"runner": {"x": before_x, "y": 1}},
            "after": {"runner": {"x": after_x, "y": 1}, "goldCount": 2},
        }
        for candidate_id, key_code, before_x, after_x in (
            ("align_ladder_25_1_right", 39, 23, 25),
            ("align_ladder_18_1_left", 37, 25, 23),
            ("align_ladder_25_1_right", 39, 23, 25),
            ("align_ladder_18_1_left", 37, 25, 23),
            ("align_ladder_25_1_right", 39, 23, 25),
            ("align_ladder_18_1_left", 37, 25, 23),
        )
    ]
    alternating_report = build_loop_report(
        {"activeDig": {}, "primaryProgressTarget": {}, "movement": {}},
        alternating_history,
    )
    assert_equal(
        predicted_horizontal_return_target(alternating_report),
        (25, 1),
        "A-B-A-B history predicts only the next return target",
    )
    ladder_row = " " * 18 + "H" + " " * 6 + "H" + " " * 4
    for god_mode in (False, True):
        alternating_state = snapshot(
            grid=[" " * 30, ladder_row, "#" * 30],
            runner={"x": 23, "y": 1, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        )
        alternating_state["godMode"] = god_mode
        alternating_state["gold"]["visiblePositions"] = []
        alternating_candidates, alternating_analysis = generate_candidates(
            alternating_state, alternating_history
        )
        alternating_ids = {
            candidate["id"] for candidate in alternating_candidates
        }
        assert_true(
            "align_ladder_25_1_right" not in alternating_ids,
            "predicted return target is suppressed for one decision",
        )
        assert_true(
            "align_ladder_18_1_left" in alternating_ids,
            "the other validated target remains available",
        )
        assert_true(
            any(
                item.get("candidateId") == "align_ladder_25_1_right"
                and item.get("disposition") == "loop_suppressed"
                and "predicted return" in str(item.get("detail"))
                for item in alternating_analysis["candidateAudit"]
            ),
            "deferred suppression remains explicit in the candidate audit",
        )

        single_target_state = deepcopy(alternating_state)
        single_target_state["terrainGrid"] = single_target_state["grid"] = [
            " " * 30,
            " " * 25 + "H" + " " * 4,
            "#" * 30,
        ]
        single_candidates, single_analysis = generate_candidates(
            single_target_state, alternating_history
        )
        assert_true(
            any(
                candidate["id"] == "align_ladder_25_1_right"
                for candidate in single_candidates
            ),
            "predicted return remains when no validated non-fallback alternative exists",
        )
        assert_true(
            all(
                item.get("candidateId") != "align_ladder_25_1_right"
                or item.get("disposition") != "loop_suppressed"
                for item in single_analysis["candidateAudit"]
            ),
            "candidate audit does not claim deferred suppression without an alternative",
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
    check_recording_pin_api()
    check_geometry_candidates()
    check_target_relative_ladder_direction()
    check_ladder_entry_discovery()
    check_post_ascent_alignment_reversal()
    check_loop_recovery()
    check_no_legacy_knowledge()
    print("backend geometry sanity ok")


if __name__ == "__main__":
    run()
