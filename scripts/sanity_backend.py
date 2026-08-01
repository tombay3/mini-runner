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
    generate_candidates,
    is_action_guard_safe,
    ladder_alignment_score,
    limit_horizontal_ticks_under_guard_pressure,
)
from agent.prompt import format_stall_report, format_state_summary  # noqa: E402
from agent.reasoning_tools import assess_guard_risk  # noqa: E402
from agent.stall_tools import build_stall_report  # noqa: E402


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
            "historyTail": [],
            "action": {"keyCode": 39, "ticks": 8, "reason": "test"},
            "stallSupervisor": {},
            "model": {"model": "openai:test", "provider": "openai"},
            "config": {"showCandidateScores": True},
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


def stall_analysis() -> dict[str, Any]:
    return {
        "goldComplete": False,
        "routeAccess": {},
        "ladder": {},
        "movement": {"canMoveLeft": True, "canMoveRight": True},
        "primaryProgressTarget": {"x": 24, "y": 12},
        "rowLadders": [],
        "nearestGold": [],
    }


def check_stall_supervisor_regressions() -> None:
    right_ladder = "align_ladder_27_14_right"
    left_ladder = "align_ladder_4_14_left"
    progressing = movement_history(
        [right_ladder] * 4,
        [(19, 14), (20, 14), (22, 14), (23, 14)],
        [39] * 4,
    )
    progressing[0]["before"]["runner"]["x"] = 17
    report = build_stall_report(stall_analysis(), progressing)
    assert_equal(report["severity"], "none", "target progress remains non-stalled")
    assert_true(report["repeatedCandidateProgress"], "target progress is recorded")
    assert_equal(report["blockedCandidateIds"], [], "non-stalled progress has no blocked ids")

    reached = movement_history(
        [right_ladder] * 4,
        [(23, 14), (25, 14), (26, 14), (27, 14)],
        [39] * 4,
    )
    reached[0]["before"]["runner"]["x"] = 22
    report = build_stall_report(stall_analysis(), reached)
    assert_equal(report["severity"], "none", "reaching macro target clears warning")
    assert_true(report["repeatedCandidateTargetReached"], "macro target completion is recorded")

    reached_after_reversals = movement_history(
        [right_ladder, right_ladder, left_ladder, right_ladder, left_ladder]
        + [right_ladder] * 3,
        [(23, 14), (25, 14), (23, 14), (25, 14), (23, 14), (25, 14), (26, 14), (27, 14)],
        [39, 39, 37, 39, 37, 39, 39, 39],
    )
    report = build_stall_report(stall_analysis(), reached_after_reversals)
    assert_equal(report["severity"], "none", "macro completion clears prior reversal warning")

    stuck = movement_history([right_ladder] * 4, [(20, 14)] * 4, [39] * 4)
    report = build_stall_report(stall_analysis(), stuck)
    assert_equal(report["severity"], "stalled", "same candidate without movement stalls")
    assert_equal(report["type"], "same_candidate_no_progress", "same candidate stall type")
    assert_true(right_ladder in report["blockedCandidateIds"], "confirmed stall blocks repeated id")

    alternating = movement_history(
        [right_ladder, left_ladder, right_ladder, left_ladder],
        [(23, 14), (25, 14), (23, 14), (25, 14)],
        [39, 37, 39, 37],
    )
    report = build_stall_report(stall_analysis(), alternating)
    assert_equal(report["severity"], "none", "short alternation remains non-stalled")
    assert_true(
        report["observations"]["shortHorizontalOscillation"],
        "short loop observation is recorded",
    )
    assert_equal(report["blockedCandidateIds"], [], "observation does not expose blocked ids")

    confirmed_loop = movement_history(
        [right_ladder, left_ladder] * 3,
        [(23, 14), (25, 14), (23, 14), (25, 14), (23, 14), (25, 14)],
        [39, 37] * 3,
    )
    confirmed_report = build_stall_report(stall_analysis(), confirmed_loop)
    assert_equal(confirmed_report["severity"], "stalled", "sustained alternation stalls")
    assert_equal(
        confirmed_report["type"], "horizontal_oscillation", "horizontal oscillation type"
    )
    assert_true(
        bool(confirmed_report["blockedCandidateKinds"]),
        "confirmed horizontal stall retains enforceable blocked kinds",
    )

    observed_analysis = stall_analysis()
    observed_analysis.update(
        {
            "runner": {"x": 25, "y": 14},
            "gold": {"remainingCount": 5, "visiblePositions": []},
            "risk": {"risk": "low", "nearestSameRowGuard": None},
            "routeAccess": {},
            "ladder": {"detail": "ladder nearby"},
            "stallReport": report,
        }
    )
    observed_prompt = format_stall_report(observed_analysis)
    state_prompt = format_state_summary(
        {"playData": 1, "level": 1, "gameStateName": "running"}, observed_analysis
    )
    assert_equal(observed_prompt, "", "trace-only observations are absent from prompt")
    assert_true("blocked:" not in state_prompt, "non-stalled state hides blocked ids")

    assert_true(
        ladder_alignment_score(5, god_mode=False, fine_align=False, stalled_target=False)
        > ladder_alignment_score(18, god_mode=False, fine_align=False, stalled_target=False),
        "near ladder outranks distant ladder",
    )
    assert_true(
        ladder_alignment_score(1, god_mode=False, fine_align=True, stalled_target=False)
        > ladder_alignment_score(2, god_mode=False, fine_align=False, stalled_target=False),
        "fine alignment remains highest near target",
    )


def check_guard_safety_regressions() -> None:
    snapshot = {
        "runner": {"x": 25, "y": 12},
        "guards": [{"x": 22, "y": 12, "actionName": "right"}],
        "terrainGrid": [" " * 28 for _ in range(16)],
    }
    risk = assess_guard_risk(snapshot)
    guard = risk["nearestSameRowGuard"]
    assert_equal(risk["risk"], "high", "three-tile same-row guard is high risk")
    assert_equal(guard["side"], "left", "guard side is relative position")
    assert_equal(guard["motion"], "right", "guard motion is separate from side")
    assert_true(guard["closing"], "right-moving guard on left is closing")
    assert_true("direction" not in guard, "ambiguous guard direction field is absent")

    analysis = {"godMode": False, "risk": risk}
    assert_true(
        not is_action_guard_safe({"keyCode": 37}, analysis),
        "normal-mode movement toward high-risk guard is unsafe",
    )
    assert_true(
        is_action_guard_safe({"keyCode": 39}, analysis),
        "normal-mode movement away from high-risk guard is safe",
    )
    medium_analysis = {
        "godMode": False,
        "risk": {
            "risk": "medium",
            "nearestSameRowGuard": {
                "x": 20,
                "distance": 4,
                "risk": "medium",
                "side": "left",
            },
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
    assert_true(
        is_action_guard_safe({"keyCode": 37}, {**analysis, "godMode": True}),
        "god mode permits progress through guard contact",
    )

    prompt_analysis = {
        "runner": {"x": 25, "y": 12},
        "gold": {"remainingCount": 4, "visiblePositions": []},
        "risk": risk,
        "movement": {},
        "ladder": {},
        "routeAccess": {},
        "stallReport": {"severity": "none", "type": None},
    }
    state_prompt = format_state_summary(
        {"playData": 1, "level": 1, "gameStateName": "running"}, prompt_analysis
    )
    assert_true('"side": "left"' in state_prompt, "prompt exposes guard side")
    assert_true('"motion": "right"' in state_prompt, "prompt exposes guard motion")
    assert_true("side is the guard's position" in state_prompt, "prompt defines side semantics")

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
    candidates, _analysis = generate_candidates(pressure_snapshot, [])
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
        "closing" in retreat["reason"] and "guard may follow" in retreat["reason"],
        "retreat explains guard motion without promising increased distance",
    )
    assert_true(
        "reassess" in retreat["goal"].lower(),
        "retreat is framed as a short reposition followed by reassessment",
    )


def run() -> None:
    check_stall_supervisor_regressions()
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
                },
            )
            assert_equal(user_record["id"], "user:first", "user record id")
            assert_equal(user_record["source"], "user", "user source")
            assert_equal(user_record["result"], "success", "user result")
            assert_equal(user_record["demo"]["time"], 16, "demo time stored")

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
            agent_record = put_record(
                client,
                {
                    "demo": demo(state=0),
                    "source": "agent",
                    "result": "failure",
                    "traceId": "trace-agent",
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
            trace_response = client.get("/api/agent/traces/trace-agent")
            assert_equal(trace_response.status_code, 200, "trace exists before delete")
            deleted_agent = client.delete("/api/recordings/1/1?traceId=trace-agent")
            assert_true(deleted_agent.get_json()["traceDeleted"], "linked trace deleted")
            missing_trace = client.get("/api/agent/traces/trace-agent")
            assert_equal(missing_trace.status_code, 404, "trace deleted")

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
            assert_equal(len(store["records"]), 10, "recording retention limit")

            trace_store = {
                "runs": {
                    f"trace-{index:02d}": {
                        "updatedAt": f"2026-01-01T00:00:{index:02d}.000Z",
                    }
                    for index in range(12)
                }
            }
            app_module.prune_trace_runs(trace_store)
            assert_equal(len(trace_store["runs"]), 10, "trace retention limit")
            assert_true("trace-11" in trace_store["runs"], "newest trace retained")
            assert_true("trace-00" not in trace_store["runs"], "oldest trace pruned")

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
