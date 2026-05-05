from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from flask import Flask, jsonify, request


app = Flask(__name__)

STORE_PATH = Path(__file__).resolve().parent / "__data1" / "recordings.json"
PUZZLE_RULES_PATH = Path(__file__).resolve().parent / "docs" / "puzzle-game.md"
STORE_VERSION = 1
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
AGENT_PLAY_DATA = 1
AGENT_LEVEL = 1
AGENT_MAX_TICKS = 20
AGENT_ALLOWED_KEYCODES = {
    "stop": 32,
    "left": 37,
    "right": 39,
    "up": 38,
    "down": 40,
    "dig_left": 90,
    "dig_right": 88,
}
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


def validate_agent_request(payload: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise ValueError("request body must be an object")
    try:
        play_data = int(payload.get("playData", 0))
        level = int(payload.get("level", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("playData and level must be integers") from exc
    if play_data != AGENT_PLAY_DATA or level != AGENT_LEVEL:
        raise ValueError("only Classic level 1 is supported")
    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be an object")
    history = payload.get("history", [])
    if not isinstance(history, list):
        raise ValueError("history must be an array")
    return snapshot, history


def normalize_agent_action(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("agent action must be an object")

    key_code = value.get("keyCode")
    if isinstance(key_code, str):
        key_code = AGENT_ALLOWED_KEYCODES.get(key_code)
    try:
        key_code = int(key_code)
    except (TypeError, ValueError) as exc:
        raise ValueError("action.keyCode must be an allowed keycode") from exc
    if key_code not in set(AGENT_ALLOWED_KEYCODES.values()):
        raise ValueError("action.keyCode is not allowed")

    try:
        ticks = int(value.get("ticks", 1))
    except (TypeError, ValueError) as exc:
        raise ValueError("action.ticks must be an integer") from exc
    ticks = max(1, min(AGENT_MAX_TICKS, ticks))

    reason = value.get("reason", "")
    return {"keyCode": key_code, "ticks": ticks, "reason": str(reason)[:500]}


def read_puzzle_rules() -> str:
    try:
        return PUZZLE_RULES_PATH.read_text(encoding="utf-8")[:6000]
    except FileNotFoundError:
        return "Collect all gold, avoid guards, use ladders/ropes, and dig traps to solve the level."


def build_agent_prompt(snapshot: dict[str, Any], history: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        [
            "You are choosing the next short Lode Runner input burst for Classic level 1.",
            "Return JSON only. Choose one allowed keycode and a tick count from 1 to 20.",
            "Allowed keycodes: stop=32, left=37, right=39, up=38, down=40, dig_left=90, dig_right=88.",
            "Game rules:\n" + read_puzzle_rules(),
            "Current live snapshot:\n" + json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
            "Recent actions:\n" + json.dumps(history[-20:], ensure_ascii=False, sort_keys=True),
        ]
    )


def extract_response_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    for item in data.get("output", []):
        for content in item.get("content", []):
            if isinstance(content.get("text"), str):
                return content["text"]
    raise ValueError("OpenAI response did not contain text output")


def call_openai_next_action(snapshot: dict[str, Any], history: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    api_key = os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("OPENAI_MODEL")
    if not api_key or not model:
        raise RuntimeError("OPENAI_API_KEY and OPENAI_MODEL are required")

    now = utc_now()
    body = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": "You are a Lode Runner planning agent. Respond with strict JSON only.",
            },
            {"role": "user", "content": build_agent_prompt(snapshot, history)},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "lode_runner_next_action",
                "strict": True,
                "schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["keyCode", "ticks", "reason"],
                    "properties": {
                        "keyCode": {
                            "type": "integer",
                            "enum": list(AGENT_ALLOWED_KEYCODES.values()),
                        },
                        "ticks": {"type": "integer"},
                        "reason": {"type": "string"},
                    },
                },
            }
        },
    }
    request_body = json.dumps(body).encode("utf-8")
    openai_request = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=request_body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(openai_request, timeout=60) as response:
        response_data = json.loads(response.read().decode("utf-8"))

    action = normalize_agent_action(json.loads(extract_response_text(response_data)))
    planner = {
        "provider": "openai",
        "model": model,
        "generatedAt": now,
        "responseId": response_data.get("id"),
    }
    return action, planner


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
