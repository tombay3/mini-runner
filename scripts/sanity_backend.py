"""Backend smoke checks; temporary stores only, no servers or model calls."""
from __future__ import annotations

import copy
import json
import math
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import AgentRequestError, validate_agent_request
from agent.candidates import generate_candidates, action_guard_safety_rejection_detail, choose_ladder_direction
from agent.reasoning_tools import get_dig_affordance
from agent.traces import serialize_step_trace
import app as backend


@contextmanager
def isolated_client():
    original = backend.STORE_PATH, backend.TRACE_STORE_PATH
    with tempfile.TemporaryDirectory() as directory:
        backend.STORE_PATH = Path(directory) / "recordings.json"
        backend.TRACE_STORE_PATH = Path(directory) / "agent-traces.json"
        try:
            yield backend.app.test_client()
        finally:
            backend.STORE_PATH, backend.TRACE_STORE_PATH = original


def check_requests(client):
    assert client.get("/api/health").get_json()["ok"] is True
    payload = {"playData": 1, "level": 1, "snapshot": {"playData": 1, "level": 1}, "history": []}
    snapshot, history, _ = validate_agent_request(payload)
    assert snapshot["level"] == 1 and history == []
    try:
        validate_agent_request({**payload, "level": 2})
    except AgentRequestError:
        pass
    else:
        raise AssertionError("Unsupported context accepted")


def check_recording_and_trace(client):
    trace_id = "smoke-run"
    step = {
        "playData": 1, "level": 1, "model": None, "config": None,
        "state": {"tick": 0, "risk": "low"},
        "action": {"keyCode": 39, "ticks": 4},
        "candidates": [], "candidateEvents": [],
        "decision": {"requestedId": None, "selectedId": None, "rationale": "", "fallback": None},
        "loop": {"active": False, "type": None},
    }
    backend.append_trace_step(trace_id, step)
    response = client.get(f"/api/agent/traces/{trace_id}")
    assert response.status_code == 200
    run = response.get_json()["run"]
    assert len(run["steps"]) == 1 and "source" not in run
    payload = {
        "source": "agent", "traceId": trace_id, "result": "failure",
        "demo": {"level": 1, "ai": 1, "time": 4, "state": 0,
                 "action": [0, 39], "goldDrop": [], "bornPos": []},
    }
    response = client.put("/api/recordings/1/1", json=payload)
    assert response.status_code == 200
    assert response.get_json()["id"] == trace_id
    assert client.get("/api/recordings/1/1").get_json()["traceId"] == trace_id
    assert client.get("/api/agent/traces/smoke-run").get_json()["run"]["outcome"]["result"] == "failure"
    assert client.get("/api/recordings/1/1/records").get_json()["count"] == 1
    pin_url = "/api/recordings/1/1/pin"
    assert client.patch(pin_url, json={"recordId": trace_id, "pinned": True}).status_code == 200
    assert backend.load_store()["records"][trace_id]["pinned"] is True
    delete_url = f"/api/recordings/1/1?recordId={trace_id}"
    assert client.delete(delete_url).status_code == 409
    assert client.delete(delete_url, json={"confirmPinnedDeletion": "true"}).status_code == 409
    assert client.delete("/api/recordings/1/1", json={"confirmPinnedDeletion": True}).status_code == 409
    assert backend.load_store()["records"][trace_id]["pinned"] is True
    assert client.get(f"/api/agent/traces/{trace_id}").status_code == 200
    assert client.delete(delete_url, json={"confirmPinnedDeletion": True}).status_code == 200
    assert backend.load_store()["records"] == {}
    assert client.get(f"/api/agent/traces/{trace_id}").status_code == 404


def candidate_snapshot(*, guarded=False, exit_state=False):
    grid = ["  H    ", "  H    ", "#######"] if exit_state else ["       ", "       ", "#######"]
    gold = {"remainingCount": 0 if exit_state else 1, "complete": exit_state,
            "visiblePositions": [] if exit_state else [{"x": 4, "y": 1}], "carriedByGuards": []}
    return {
        "playData": 1, "level": 1, "tick": 0, "gameStateName": "running", "godMode": False,
        "runner": {"x": 2, "y": 1, "xOffset": 0, "yOffset": 0, "actionName": "stop"},
        "guards": [{"id": 0, "x": 5, "y": 1, "xOffset": 0, "yOffset": 0,
                    "actionName": "left", "hasGold": 0}] if guarded else [],
        "gold": gold, "goldCount": gold["remainingCount"], "goldComplete": exit_state,
        "terrainGrid": grid, "grid": grid, "openHoles": [], "activeDig": None,
    }


def check_candidate_output():
    for options in ({}, {"guarded": True}, {"exit_state": True}):
        state = candidate_snapshot(**options)
        original = copy.deepcopy(state)
        pool, analysis = generate_candidates(state, [], limit=7, max_action_ticks=20)
        assert state == original
        assert 0 < len(pool) <= 7
        assert len({c["id"] for c in pool}) == len(pool)
        for candidate in pool:
            assert isinstance(candidate["id"], str)
            assert candidate["lane"] in {"safety", "progress", "environment"}
            assert type(candidate["score"]) in {int, float} and math.isfinite(candidate["score"])
            action = candidate["firstAction"]
            assert action["keyCode"] in {32, 37, 38, 39, 40, 88, 90}
            assert type(action["ticks"]) is int and 1 <= action["ticks"] <= 20
        selected = pool[0]
        trace = serialize_step_trace(
            snapshot=state, action=selected["firstAction"], candidates=pool,
            selected_candidate=selected, analysis=analysis,
            validation={"requestedCandidateId": selected["id"], "fallbackUsed": False},
        )
        assert trace["decision"]["selectedId"] == selected["id"]
        assert trace["action"] == {k: selected["firstAction"][k] for k in ("keyCode", "ticks")}
        json.dumps(trace, allow_nan=False)


def check_vertical_secondary_safety():
    analysis = {
        "godMode": False, "runner": {"action": "stop"},
        "risk": {
            "pressureGuard": {"id": 0, "risk": "high", "relativeX": "right",
                              "relativeY": "same", "distance": 2, "motion": "left"},
            "nearbyGuards": [{"id": 1, "risk": "high", "relativeX": "same",
                              "relativeY": "below", "motion": "up"}],
        },
    }
    original = copy.deepcopy(analysis)
    for key, side, approaching, departing in ((40, "below", "up", "down"),
                                             (38, "above", "down", "up")):
        threat = analysis["risk"]["nearbyGuards"][0]
        threat.update(relativeY=side, motion=approaching)
        action = {"keyCode": key, "ticks": 6}
        for kind in ("retreat_from_guard", "descend_route", "climb_ladder"):
            assert action_guard_safety_rejection_detail(action, analysis, candidate_kind=kind)
        threat["motion"] = departing
        assert action_guard_safety_rejection_detail(action, analysis, candidate_kind="climb_ladder") is None
        threat.update(motion=approaching, relativeX="left")
        assert action_guard_safety_rejection_detail(action, analysis, candidate_kind="descend_route") is None
        threat["relativeX"] = "same"
        analysis["godMode"] = True
        assert action_guard_safety_rejection_detail(action, analysis, candidate_kind="descend_route") is None
        analysis["godMode"] = False
    # Safety validation must not modify its inputs.
    unchanged = copy.deepcopy(original)
    action_guard_safety_rejection_detail({"keyCode": 40, "ticks": 6}, unchanged)
    assert unchanged == original


def check_short_medium_clearance():
    # The same bounded movement must be safe in either direction and at any
    # column. Two-sided pressure is checked before granting the exception.
    for direction in (-1, 1):
        analysis = {
            "runner": {"x": 12, "xOffset": 0},
            "risk": {"risk": "medium", "pressureGuard": {
                "id": 0, "x": 12 + 4 * direction, "xOffset": 0,
                "risk": "medium", "relativeX": "left" if direction < 0 else "right",
                "relativeY": "same", "distance": 4,
            }, "nearbyGuards": []},
        }
        threat = analysis["risk"]["pressureGuard"]
        analysis["risk"]["nearbyGuards"] = [threat]
        action = {"keyCode": 37 if direction < 0 else 39, "ticks": 4}
        original = copy.deepcopy(analysis)
        assert action_guard_safety_rejection_detail(action, analysis) is None
        assert analysis == original
        assert action_guard_safety_rejection_detail({**action, "ticks": 6}, analysis)
        # Offsets can consume the apparent tile-level clearance.
        threat["xOffset"] = -17 * direction
        assert action_guard_safety_rejection_detail(action, analysis)
        threat["xOffset"] = 0
        threat["risk"] = "high"
        assert action_guard_safety_rejection_detail(action, analysis)
        threat["risk"] = "medium"
        del threat["xOffset"]
        assert action_guard_safety_rejection_detail(action, analysis)
        threat["xOffset"] = 0
        analysis["risk"]["nearbyGuards"].append({
            "id": 1, "x": 12 - 2 * direction, "xOffset": 0,
            "risk": "medium", "relativeY": "same",
            "relativeX": "right" if direction < 0 else "left",
        })
        assert action_guard_safety_rejection_detail(action, analysis)
        analysis["godMode"] = True
        assert action_guard_safety_rejection_detail(action, analysis) is None


def check_shorter_medium_candidates():
    for direction in (-1, 1):
        state = candidate_snapshot(guarded=True)
        state["runner"]["x"] = 2 if direction == 1 else 4
        state["gold"]["visiblePositions"][0]["x"] = 4 if direction == 1 else 2
        guard = state["guards"][0]
        guard.update(x=6 if direction == 1 else 0, xOffset=-17 * direction,
                     actionName="left" if direction == 1 else "right")
        original = copy.deepcopy(state)
        pool, analysis = generate_candidates(state, [])
        progress = next(c for c in pool if c["kind"] == "collect_same_row_gold")
        assert progress["firstAction"]["ticks"] == 3
        assert progress["firstAction"]["keyCode"] == (39 if direction == 1 else 37)
        assert action_guard_safety_rejection_detail(progress["firstAction"], analysis,
                                                  candidate_kind=progress["kind"]) is None
        assert action_guard_safety_rejection_detail({**progress["firstAction"], "ticks": 4},
                                                  analysis, candidate_kind=progress["kind"])
        assert state == original
        guard["xOffset"] = 0
        unchanged, _ = generate_candidates(state, [])
        control = next(c for c in unchanged if c["id"] == progress["id"])
        assert control["firstAction"]["ticks"] == 4
        assert control["score"] == progress["score"]
        # Near high-risk pressure must still exclude progress, at any duration.
        guard["x"] = state["runner"]["x"] + 2 * direction
        blocked, _ = generate_candidates(state, [])
        assert not any(c["kind"] == "collect_same_row_gold" for c in blocked)
        state["godMode"] = True
        god, _ = generate_candidates(state, [])
        assert next(c for c in god if c["kind"] == "collect_same_row_gold")["firstAction"]["ticks"] == 8


def check_defensive_dig_threat_priority():
    state = candidate_snapshot()
    state["gold"]["visiblePositions"] = []
    descending = {"relativeX": "right", "relativeY": "above", "motion": "down", "distance": 2}
    same_row = {"relativeX": "left", "relativeY": "same", "distance": 4}
    risk = {"pressureGuard": descending, "nearbyGuards": [descending, same_row]}
    assert get_dig_affordance(state, risk=risk)["right"]["guardCouldFall"]
    same_row["distance"] = 1
    dig = get_dig_affordance(state, risk=risk)
    assert dig["left"]["guardCouldFall"] and not dig["right"]["guardCouldFall"]


def check_targetless_ladder_continuation():
    state = candidate_snapshot()
    state.update(terrainGrid=["     ", "  H  ", "  H  ", "  H  ", "#####"], tick=6)
    state["grid"] = state["terrainGrid"]
    state["runner"].update(y=1, yOffset=10, actionName="down")
    state["gold"]["visiblePositions"] = []
    history = [{"candidateId": "descend_route_2_1_down", "keyCode": 40, "ticks": 6,
                "tick": 0, "afterTick": 6,
                "before": {"runner": {"x": 2, "y": 0, "xOffset": 0, "yOffset": 0}, "goldCount": 1},
                "after": {"runner": copy.deepcopy(state["runner"]), "goldCount": 1}}]
    original = copy.deepcopy((state, history))
    for god_mode in (False, True):
        state["godMode"] = god_mode
        pool, analysis = generate_candidates(state, history)
        assert any(c["kind"] == "climb_ladder" and c["firstAction"]["keyCode"] == 40 for c in pool)
        assert not any(c["kind"] == "climb_ladder" and c["firstAction"]["keyCode"] == 38 for c in pool)
        assert analysis["ladder"]["recommendedAction"] == "down"
        # A visible target or exit priority must still override continuation.
        analysis["primaryProgressTarget"] = {"x": 2, "y": 0}
        assert choose_ladder_direction(state, analysis, history) == "up"
        analysis["primaryProgressTarget"] = {}
        analysis["goldComplete"] = True
        assert choose_ladder_direction(state, analysis, history) == "up"
        analysis["goldComplete"] = False
        # Guard pressure, blocked movement and stale/non-progress history do not
        # qualify for the no-target direction tie-break.
        analysis["risk"]["risk"] = "medium"
        assert choose_ladder_direction(state, analysis, history) == "up"
        analysis["risk"]["risk"] = "low"
        analysis["movement"]["canMoveDown"] = False
        assert choose_ladder_direction(state, analysis, history) == "up"
        analysis["movement"]["canMoveDown"] = True
        for edit in ({"candidateId": "retreat_from_guard_down"}, {"afterTick": 5},
                     {"before": history[0]["after"]}):
            assert choose_ladder_direction(state, analysis, [{**history[0], **edit}]) == "up"
        assert choose_ladder_direction(state, analysis, []) == "up"
        upward = copy.deepcopy(history)
        upward[0].update(candidateId="climb_ladder_2_2_up", keyCode=38)
        upward[0]["before"]["runner"].update(y=2, yOffset=0)
        assert choose_ladder_direction(state, analysis, upward) == "up"
    state["godMode"] = False
    assert (state, history) == original
    # A real approaching guard still determines the safe vertical candidates.
    state["guards"] = [{"id": 0, "x": 2, "y": 2, "xOffset": 0, "yOffset": 0,
                        "actionName": "up", "hasGold": 0}]
    pool, analysis = generate_candidates(state, history)
    assert analysis["risk"]["risk"] in {"high", "critical"}
    assert any(c["firstAction"]["keyCode"] == 38 for c in pool)
    assert not any(c["firstAction"]["keyCode"] == 40 for c in pool)
    assert analysis["ladder"]["recommendedAction"] == "up"


def check_off_center_pinch_dig():
    state = candidate_snapshot()
    state["runner"].update(x=5, xOffset=8)
    state["terrainGrid"] = state["grid"] = ["           ", "           ",
                                            "###########", "@@@@@@@@@@@"]
    state["gold"]["visiblePositions"] = [{"x": 1, "y": 1}]
    state["guards"] = [
        {"id": 0, "x": 0, "y": 1, "xOffset": 8, "yOffset": 0,
         "actionName": "right", "hasGold": 0},
        {"id": 1, "x": 9, "y": 1, "xOffset": 0, "yOffset": 17,
         "actionName": "climb_out", "hasGold": 0},
    ]
    original = copy.deepcopy(state)
    pool, _ = generate_candidates(state, [])
    assert any(c["kind"] == "retreat_from_guard" for c in pool)
    assert any(c["kind"] == "defensive_dig" and c["firstAction"]["keyCode"] == 88
               for c in pool)
    assert state == original
    state["guards"] = state["guards"][1:]
    _, analysis = generate_candidates(state, [])
    assert not analysis["dig"]["right"]["canDefensiveDig"]
    state = copy.deepcopy(original)
    state["godMode"] = True
    _, analysis = generate_candidates(state, [])
    assert not analysis["dig"]["right"]["canDefensiveDig"]


def check_retention():
    records = {
        str(i): {"id": str(i), "traceId": str(i), "source": "agent",
                 "pinned": i == 0, "savedAt": f"2026-01-01T00:00:{i:02d}Z"}
        for i in range(13)
    }
    recordings = {"records": records}
    traces = {"runs": {id: {"steps": [], "updatedAt": r["savedAt"]} for id, r in records.items()}}
    backend.prune_recordings(recordings)
    backend.prune_trace_runs(traces, backend.pinned_trace_ids_from_store(recordings))
    expected = {"0"} | {str(i) for i in range(3, 13)}
    assert set(recordings["records"]) == set(traces["runs"]) == expected


if __name__ == "__main__":
    with isolated_client() as client:
        check_requests(client)
        check_recording_and_trace(client)
        check_retention()
        check_candidate_output()
        check_vertical_secondary_safety()
        check_short_medium_clearance()
        check_shorter_medium_candidates()
        check_defensive_dig_threat_priority()
        check_targetless_ladder_continuation()
        check_off_center_pinch_dig()
    print("backend smoke ok")
