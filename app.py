from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from flask import Flask, jsonify, request

from agent import (
    AGENT_LEVEL,
    AGENT_PLAY_DATA,
    AgentConfigError,
    AgentExecutionError,
    AgentRequestError,
    plan_next_action,
    validate_agent_request,
)
from agent.logging_utils import configure_logging, get_logger, log_event, normalize_flask_logger


if "--debug" in sys.argv:
    sys.argv.remove("--debug")
    os.environ["AGENT_DEBUG_LOG"] = "1"
    os.environ["APP_LOG_LEVEL"] = "DEBUG"

configure_logging()
LOGGER = get_logger("app")

app = Flask(__name__)
normalize_flask_logger(app)

STORE_PATH = Path(__file__).resolve().parent / "__data1" / "recordings.json"
TRACE_STORE_PATH = Path(__file__).resolve().parent / "__data1" / "agent-traces.json"
STORE_VERSION = 1
TRACE_STORE_VERSION = 1
TRACE_RUN_LIMIT = 10
RECORDING_RUN_LIMIT = 10
_store_lock = Lock()
_trace_store_lock = Lock()

log_event(
    LOGGER,
    logging.INFO,
    "backend_startup_complete",
    store_path=STORE_PATH.name,
    trace_store_path=TRACE_STORE_PATH.name,
    app_log_level=os.environ.get("APP_LOG_LEVEL", "INFO").upper(),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def empty_store() -> dict[str, Any]:
    return {"version": STORE_VERSION, "updatedAt": None, "records": {}}


def empty_trace_store() -> dict[str, Any]:
    return {"version": TRACE_STORE_VERSION, "updatedAt": None, "runs": {}}


def normalize_id(value: str, name: str) -> str:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return str(parsed)


def load_json_store(path: Path, empty_factory) -> dict[str, Any]:
    if not path.exists():
        return empty_factory()
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:
        log_event(LOGGER, logging.ERROR, "json_store_load_failed", path=path.name, error=exc)
        raise
    if not isinstance(data, dict):
        return empty_factory()
    return data


def save_json_store(path: Path, store: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(store, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_path, path)
    except Exception as exc:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        log_event(LOGGER, logging.ERROR, "json_store_save_failed", path=path.name, error=exc)
        raise


def load_store() -> dict[str, Any]:
    data = load_json_store(STORE_PATH, empty_store)
    data.setdefault("version", STORE_VERSION)
    data.setdefault("updatedAt", None)
    if not isinstance(data.get("records"), dict):
        data["records"] = {}
    return data


def save_store(store: dict[str, Any]) -> None:
    save_json_store(STORE_PATH, store)


def recording_sort_key(record: dict[str, Any]) -> str:
    value = record.get("savedAt") or ""
    return str(value)


def sorted_record_items(records: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    retained = sorted(
        (
            (index, str(record_id), record)
            for index, (record_id, record) in enumerate(records.items())
            if isinstance(record, dict)
        ),
        key=lambda item: (recording_sort_key(item[2]), item[0]),
        reverse=True,
    )
    return [(record_id, record) for _index, record_id, record in retained]


def prune_recordings(store: dict[str, Any]) -> None:
    records = store.get("records")
    if not isinstance(records, dict):
        store["records"] = {}
        return
    store["records"] = dict(sorted_record_items(records)[:RECORDING_RUN_LIMIT])


def find_latest_recording(store: dict[str, Any], play_data: str, level: str) -> dict[str, Any] | None:
    records = store.get("records", {})
    if not isinstance(records, dict):
        return None
    for _record_id, record in sorted_record_items(records):
        if str(record.get("playData")) == play_data and str(record.get("level")) == level:
            return record
    return None


def find_recordings(store: dict[str, Any], play_data: str, level: str) -> list[dict[str, Any]]:
    records = store.get("records", {})
    if not isinstance(records, dict):
        return []
    return [
        record
        for _record_id, record in sorted_record_items(records)
        if str(record.get("playData")) == play_data and str(record.get("level")) == level
    ]


def delete_trace_run(trace_id: str | None) -> bool:
    if not trace_id:
        return False
    with _trace_store_lock:
        store = load_trace_store()
        existed = store["runs"].pop(trace_id, None) is not None
        if existed:
            store["updatedAt"] = utc_now()
            save_trace_store(store)
        return existed


def load_trace_store() -> dict[str, Any]:
    data = load_json_store(TRACE_STORE_PATH, empty_trace_store)
    data.setdefault("version", TRACE_STORE_VERSION)
    data.setdefault("updatedAt", None)
    if not isinstance(data.get("runs"), dict):
        data["runs"] = {}
    return data


def save_trace_store(store: dict[str, Any]) -> None:
    save_json_store(TRACE_STORE_PATH, store)


def validate_demo(demo: Any) -> dict[str, Any]:
    if not isinstance(demo, dict):
        raise ValueError("demo must be an object")
    for key in ("level", "ai", "time", "state", "action", "goldDrop", "bornPos"):
        if key not in demo:
            raise ValueError(f"demo.{key} is required")
    for key in ("action", "goldDrop", "bornPos"):
        if not isinstance(demo[key], list):
            raise ValueError(f"demo.{key} must be an array")
    return demo


def validate_source(value: Any) -> str:
    if value is None:
        return "user"
    if value not in {"user", "agent"}:
        raise ValueError("source must be user or agent")
    return value


def validate_result(value: Any, demo: dict[str, Any]) -> str:
    if value is None:
        return "success" if int(demo.get("state", 0)) == 1 else "failure"
    if value not in {"success", "failure"}:
        raise ValueError("result must be success or failure")
    return value


def validate_solver(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("solver must be an object")

    allowed_keys = {
        "modelProfile",
        "provider",
        "model",
        "generatedAt",
        "responseId",
        "traceId",
        "failureReason",
    }
    solver = {key: value[key] for key in allowed_keys if key in value and value[key] is not None}
    for key in ("modelProfile", "provider", "model", "responseId", "traceId", "failureReason"):
        if key in solver and not isinstance(solver[key], str):
            raise ValueError(f"solver.{key} must be a string")
    if "generatedAt" in solver and not isinstance(solver["generatedAt"], (int, float, str)):
        raise ValueError("solver.generatedAt must be a number or string")
    return solver or None


def validate_trace_id(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("traceId must be a string")
    return value.strip()


def validate_record_id(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("id must be a string")
    return value.strip()


def trace_model_summary(planner: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(planner, dict):
        return None
    summary = {
        key: planner.get(key)
        for key in ("modelProfile", "provider", "model", "modelSource")
        if planner.get(key) is not None
    }
    return summary or None


def trace_sort_key(run: dict[str, Any]) -> str:
    value = run.get("updatedAt") or run.get("createdAt") or ""
    return str(value)


def prune_trace_runs(store: dict[str, Any]) -> None:
    runs = store.get("runs", {})
    if not isinstance(runs, dict) or len(runs) <= TRACE_RUN_LIMIT:
        return
    retained = sorted(
        runs.items(),
        key=lambda item: trace_sort_key(item[1]) if isinstance(item[1], dict) else "",
        reverse=True,
    )[:TRACE_RUN_LIMIT]
    store["runs"] = dict(retained)


def summarize_trace_run(trace_id: str, run: dict[str, Any]) -> dict[str, Any]:
    return {
        "traceId": trace_id,
        "playData": run.get("playData"),
        "level": run.get("level"),
        "createdAt": run.get("createdAt"),
        "updatedAt": run.get("updatedAt"),
        "stepCount": run.get("stepCount", 0),
        "latestAction": run.get("latestAction"),
        "model": run.get("model"),
    }


def summarize_record_trace(record: dict[str, Any], trace_store: dict[str, Any]) -> dict[str, Any] | None:
    trace_id = record.get("traceId")
    if not isinstance(trace_id, str) or not trace_id:
        return None
    runs = trace_store.get("runs", {})
    if not isinstance(runs, dict):
        return None
    run = runs.get(trace_id)
    if not isinstance(run, dict):
        return None
    return {
        "traceId": trace_id,
        "createdAt": run.get("createdAt"),
        "updatedAt": run.get("updatedAt"),
        "stepCount": run.get("stepCount", 0),
        "latestAction": run.get("latestAction"),
        "model": run.get("model"),
    }


def find_latest_trace_run(store: dict[str, Any], play_data: str, level: str) -> dict[str, Any] | None:
    latest: tuple[str, dict[str, Any]] | None = None
    runs = store.get("runs", {})
    if not isinstance(runs, dict):
        return None

    for trace_id, run in runs.items():
        if not isinstance(run, dict):
            continue
        if str(run.get("playData")) != play_data or str(run.get("level")) != level:
            continue
        if latest is None or trace_sort_key(run) > trace_sort_key(latest[1]):
            latest = (trace_id, run)
    if latest is None:
        return None
    return summarize_trace_run(*latest)


def append_trace_step(run_id: str, step_trace: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()

    with _trace_store_lock:
        store = load_trace_store()
        run = store["runs"].get(run_id)
        if run is None:
            run = {
                "id": run_id,
                "createdAt": step_trace.get("createdAt", now),
                "updatedAt": now,
                "playData": step_trace["playData"],
                "level": step_trace["level"],
                "model": trace_model_summary(step_trace.get("planner")),
                "steps": [],
            }
            store["runs"][run_id] = run
        step_index = len(run["steps"])
        stored_step = dict(step_trace)
        stored_step["stepIndex"] = step_index
        run["steps"].append(stored_step)
        run["updatedAt"] = now
        run["stepCount"] = len(run["steps"])
        run["latestAction"] = stored_step.get("action")
        run["model"] = trace_model_summary(stored_step.get("planner"))

        prune_trace_runs(store)
        store["updatedAt"] = now
        save_trace_store(store)
        return store["runs"][run_id]


@app.get("/api/health")
def health():
    return jsonify({"ok": True})


@app.get("/api/recordings")
def get_recordings():
    with _store_lock:
        return jsonify(load_store())


@app.get("/api/recordings/<play_data>/<level>")
def get_recording(play_data: str, level: str):
    try:
        play_data_key = normalize_id(play_data, "playData")
        level_key = normalize_id(level, "level")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    with _store_lock:
        store = load_store()
        record = find_latest_recording(store, play_data_key, level_key)
    if record is None:
        return jsonify({"error": "recording not found"}), 404
    return jsonify(record)


@app.get("/api/recordings/<play_data>/<level>/records")
def get_recording_records(play_data: str, level: str):
    try:
        play_data_key = normalize_id(play_data, "playData")
        level_key = normalize_id(level, "level")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    with _store_lock:
        recording_store = load_store()
        records = find_recordings(recording_store, play_data_key, level_key)
    with _trace_store_lock:
        trace_store = load_trace_store()

    joined_records = []
    for record in records:
        joined = dict(record)
        joined["trace"] = summarize_record_trace(record, trace_store)
        joined_records.append(joined)
    return jsonify({"records": joined_records, "count": len(joined_records)})


@app.put("/api/recordings/<play_data>/<level>")
def put_recording(play_data: str, level: str):
    try:
        play_data_key = normalize_id(play_data, "playData")
        level_key = normalize_id(level, "level")
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ValueError("request body must be an object")
        demo = validate_demo(payload.get("demo", payload))
        source = validate_source(payload.get("source"))
        result = validate_result(payload.get("result"), demo)
        solver = validate_solver(payload.get("solver"))
        trace_id = validate_trace_id(payload.get("traceId", payload.get("traceRef")))
        record_id = validate_record_id(payload.get("id"))
        if source == "agent" and trace_id is None:
            raise ValueError("agent recording requires traceId")
        if source == "agent" and record_id is not None and record_id != trace_id:
            raise ValueError("agent recording id must match traceId")
    except ValueError as exc:
        log_event(
            LOGGER,
            logging.WARNING,
            "recording_request_invalid",
            play_data=play_data,
            level=level,
            error=exc,
        )
        return jsonify({"error": str(exc)}), 400

    now = utc_now()
    record_id = trace_id if source == "agent" else record_id or f"user:{now}"
    record = {
        "id": record_id,
        "playData": int(play_data_key),
        "level": int(level_key),
        "savedAt": now,
        "source": source,
        "result": result,
        "demo": demo,
    }
    if solver is not None:
        record["solver"] = solver
    if trace_id is not None:
        record["traceId"] = trace_id

    with _store_lock:
        try:
            store = load_store()
            store["version"] = STORE_VERSION
            store["updatedAt"] = now
            store["records"][record_id] = record
            prune_recordings(store)
            save_store(store)
        except Exception as exc:
            log_event(
                LOGGER,
                logging.ERROR,
                "recording_persist_failed",
                play_data=play_data_key,
                level=level_key,
                source=source,
                result=result,
                error=exc,
            )
            return jsonify({"error": "failed to persist recording"}), 500

    if source == "agent":
        log_event(
            LOGGER,
            logging.INFO,
            "agent_recording_saved",
            play_data=play_data_key,
            level=level_key,
            result=result,
            trace_id=trace_id,
            model=(solver or {}).get("model"),
        )

    return jsonify(record)


@app.post("/api/agent/next-action")
def next_agent_action():
    payload = request.get_json(silent=True)
    try:
        snapshot, history, options = validate_agent_request(payload)
        run_id = options.get("runId") or f"trace-{utc_now()}"
        plan = plan_next_action(snapshot, history, options)
    except AgentRequestError as exc:
        log_event(
            LOGGER,
            logging.WARNING,
            "agent_request_invalid",
            trace_id=(payload or {}).get("runId"),
            error=exc,
        )
        return jsonify({"error": str(exc)}), 400
    except AgentConfigError as exc:
        log_event(
            LOGGER,
            logging.ERROR,
            "agent_config_error",
            trace_id=(payload or {}).get("runId"),
            error=exc,
        )
        return jsonify({"error": str(exc)}), 503
    except AgentExecutionError as exc:
        log_event(
            LOGGER,
            logging.ERROR,
            "agent_execution_failed",
            trace_id=(payload or {}).get("runId"),
            error=exc,
        )
        return jsonify({"error": "agent execution failed", "detail": str(exc)}), 502

    step_trace = dict(plan["trace"])
    step_trace["playData"] = snapshot.get("playData", 1)
    step_trace["level"] = snapshot.get("level", 1)
    try:
        run = append_trace_step(run_id, step_trace)
    except Exception as exc:
        log_event(
            LOGGER,
            logging.ERROR,
            "agent_trace_persist_failed",
            trace_id=run_id,
            play_data=step_trace["playData"],
            level=step_trace["level"],
            error=exc,
        )
        return jsonify({"error": "failed to persist agent trace"}), 500

    log_event(
        LOGGER,
        logging.INFO,
        "agent_step_selected",
        trace_id=run_id,
        play_data=step_trace["playData"],
        level=step_trace["level"],
        model=plan["planner"].get("model"),
        model_profile=plan["planner"].get("modelProfile"),
        key_code=plan["action"].get("keyCode"),
        ticks=plan["action"].get("ticks"),
        candidate_id=plan.get("candidateId"),
        step_count=run.get("stepCount"),
    )

    return jsonify(
        {
            "action": plan["action"],
            "planner": plan["planner"],
            "traceId": run_id,
            "stepCount": run.get("stepCount"),
            "candidateId": plan.get("candidateId"),
            "candidate": plan.get("candidate"),
            "candidates": plan.get("candidates"),
            "validation": plan.get("validation"),
        }
    )


@app.get("/api/agent/traces/<trace_id>")
def get_agent_trace(trace_id: str):
    with _trace_store_lock:
        store = load_trace_store()
        run = store["runs"].get(trace_id)
    if run is None:
        return jsonify({"error": "trace not found"}), 404
    return jsonify(run)


@app.get("/api/agent/runs/<play_data>/<level>")
def get_agent_run(play_data: str, level: str):
    try:
        play_data_key = normalize_id(play_data, "playData")
        level_key = normalize_id(level, "level")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    with _trace_store_lock:
        trace_store = load_trace_store()
        latest_run = find_latest_trace_run(trace_store, play_data_key, level_key)
    with _store_lock:
        recording_store = load_store()
        recording = find_latest_recording(recording_store, play_data_key, level_key)
    if latest_run is None and recording is None:
        return jsonify({"error": "agent run not found"}), 404
    return jsonify({"latestRun": latest_run, "recording": recording})


@app.delete("/api/recordings/<play_data>/<level>")
def delete_recording(play_data: str, level: str):
    try:
        play_data_key = normalize_id(play_data, "playData")
        level_key = normalize_id(level, "level")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    selected_trace_id = request.args.get("traceId") or None
    selected_record_id = request.args.get("recordId") or selected_trace_id
    deleted_trace_id = None
    latest_record = None
    with _store_lock:
        store = load_store()
        records = store.get("records", {})
        existed = False
        if isinstance(records, dict):
            if selected_record_id:
                record_key = selected_record_id
                candidate = records.get(record_key)
                record = (
                    records.pop(record_key)
                    if isinstance(candidate, dict)
                    and str(candidate.get("playData")) == play_data_key
                    and str(candidate.get("level")) == level_key
                    else None
                )
            else:
                record = find_latest_recording(store, play_data_key, level_key)
                record_key = record.get("id") if isinstance(record, dict) else None
                if record_key:
                    record = records.pop(str(record_key), None)
            existed = isinstance(record, dict)
            deleted_trace_id = record.get("traceId") if existed else selected_trace_id
            prune_recordings(store)
            latest_record = find_latest_recording(store, play_data_key, level_key)
        store["updatedAt"] = utc_now()
        save_store(store)

    trace_deleted = delete_trace_run(deleted_trace_id) if existed else False
    return jsonify(
        {
            "deleted": existed,
            "traceDeleted": trace_deleted,
            "traceId": deleted_trace_id,
            "latestRecord": latest_record,
        }
    )


if __name__ == "__main__":
    app.run(host="localhost", port=8080)
