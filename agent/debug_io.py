from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parent.parent
DEBUG_LOG_PATH = ROOT_DIR / "__data1" / "agent-debug.log"
DEBUG_ENTRY_LIMIT = 10
ENTRY_PREFIX = "===== agent-model-io "


def is_debug_enabled() -> bool:
    return os.environ.get("AGENT_DEBUG_LOG", "").strip().lower() in {"1", "true", "yes", "on"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def append_model_io_debug(
    *,
    trace_id: str | None,
    model: str,
    retry: bool,
    prompt: str,
    response: Any,
    parse_error: str | None,
    selected_candidate_id: str | None,
) -> None:
    if not is_debug_enabled():
        return

    DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = format_model_io_entry(
        trace_id=trace_id,
        model=model,
        retry=retry,
        prompt=prompt,
        response=response,
        parse_error=parse_error,
        selected_candidate_id=selected_candidate_id,
    )
    entries = read_debug_entries()
    entries.append(entry)
    retained = entries[-DEBUG_ENTRY_LIMIT:]
    DEBUG_LOG_PATH.write_text("\n".join(retained).rstrip() + "\n", encoding="utf-8")


def read_debug_entries() -> list[str]:
    if not DEBUG_LOG_PATH.exists():
        return []
    content = DEBUG_LOG_PATH.read_text(encoding="utf-8")
    entries = []
    for chunk in content.split(ENTRY_PREFIX):
        chunk = chunk.strip()
        if chunk:
            entries.append(f"{ENTRY_PREFIX}{chunk}\n")
    return entries


def format_model_io_entry(
    *,
    trace_id: str | None,
    model: str,
    retry: bool,
    prompt: str,
    response: Any,
    parse_error: str | None,
    selected_candidate_id: str | None,
) -> str:
    message = get_response_message(response)
    return "\n".join(
        [
            f"{ENTRY_PREFIX}{utc_now()} =====",
            f"traceId: {trace_id or ''}",
            f"model: {model}",
            f"retry: {str(retry).lower()}",
            f"selectedCandidateId: {selected_candidate_id or ''}",
            f"parseError: {parse_error or ''}",
            "",
            "--- prompt ---",
            prompt,
            "",
            "--- finalMessage.content ---",
            format_message_attr(message, "content"),
            "",
            "--- finalMessage.reasoning_content ---",
            format_message_attr(message, "reasoning_content"),
            "",
        ]
    )


def get_response_message(response: Any) -> Any:
    choices = getattr(response, "choices", None)
    if not choices:
        return None
    return getattr(choices[0], "message", None)


def format_message_attr(message: Any, name: str) -> str:
    value = getattr(message, name, None)
    if value is None:
        return ""
    text = str(value)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text
    return json.dumps(parsed, indent=2, sort_keys=True)
