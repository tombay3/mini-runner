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


def run() -> None:
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
