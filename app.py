from __future__ import annotations

import json
import tempfile
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from flask import Flask, jsonify, request

from agent import call_openai_next_action, validate_agent_request


app = Flask(__name__)

STORE_PATH = Path(__file__).resolve().parent / "__data1" / "recordings.json"
STORE_VERSION = 1
_store_lock = Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def empty_store() -> dict[str, Any]:
    return {"version": STORE_VERSION, "updatedAt": None, "recordings": {}}


def normalize_id(value: str, name: str) -> str:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return str(parsed)


def load_store() -> dict[str, Any]:
    if not STORE_PATH.exists():
        return empty_store()
    with STORE_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return empty_store()
    data.setdefault("version", STORE_VERSION)
    data.setdefault("updatedAt", None)
    if not isinstance(data.get("recordings"), dict):
        data["recordings"] = {}
    return data


def save_store(store: dict[str, Any]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{STORE_PATH.name}.",
        suffix=".tmp",
        dir=STORE_PATH.parent,
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(store, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_path, STORE_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


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
    return value


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
        record = store["recordings"].get(play_data_key, {}).get(level_key)
    if record is None:
        return jsonify({"error": "recording not found"}), 404
    return jsonify(record)


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
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    now = utc_now()
    record = {
        "playData": int(play_data_key),
        "level": int(level_key),
        "savedAt": now,
        "source": source,
        "result": result,
        "demo": demo,
    }
    if solver is not None:
        record["solver"] = solver

    with _store_lock:
        store = load_store()
        store["version"] = STORE_VERSION
        store["updatedAt"] = now
        store["recordings"].setdefault(play_data_key, {})[level_key] = record
        save_store(store)

    return jsonify(record)


@app.post("/api/agent/next-action")
def next_agent_action():
    try:
        snapshot, history = validate_agent_request(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    try:
        action, planner = call_openai_next_action(snapshot, history)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503
    except urllib.error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="replace")
        return jsonify({"error": "OpenAI request failed", "detail": message}), 502
    except (urllib.error.URLError, TimeoutError) as exc:
        return jsonify({"error": "OpenAI request failed", "detail": str(exc)}), 502
    except (json.JSONDecodeError, ValueError) as exc:
        return jsonify({"error": "invalid OpenAI action", "detail": str(exc)}), 502

    return jsonify({"action": action, "planner": planner})


@app.delete("/api/recordings/<play_data>/<level>")
def delete_recording(play_data: str, level: str):
    try:
        play_data_key = normalize_id(play_data, "playData")
        level_key = normalize_id(level, "level")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    with _store_lock:
        store = load_store()
        version_records = store["recordings"].get(play_data_key, {})
        existed = level_key in version_records
        version_records.pop(level_key, None)
        if not version_records:
            store["recordings"].pop(play_data_key, None)
        store["updatedAt"] = utc_now()
        save_store(store)

    return jsonify({"deleted": existed})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
