from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone

from .config import AGENT_ALLOWED_KEYCODES, OPENAI_RESPONSES_URL, get_openai_api_key, get_openai_model
from .prompt import build_agent_prompt
from .validation import normalize_agent_action


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def extract_response_text(data: dict) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    for item in data.get("output", []):
        for content in item.get("content", []):
            if isinstance(content.get("text"), str):
                return content["text"]
    raise ValueError("OpenAI response did not contain text output")


def call_openai_next_action(snapshot: dict, history: list[dict]) -> tuple[dict, dict]:
    api_key = get_openai_api_key()
    model = get_openai_model()
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
                        "keyCode": {"type": "integer", "enum": list(AGENT_ALLOWED_KEYCODES.values())},
                        "ticks": {"type": "integer"},
                        "reason": {"type": "string"},
                    },
                },
            }
        },
    }

    openai_request = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(body).encode("utf-8"),
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
