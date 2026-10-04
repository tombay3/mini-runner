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
from agent.candidates import generate_candidates
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
    print("backend smoke ok")
