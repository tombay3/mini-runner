from __future__ import annotations

import json
from typing import Any

from aisuite.provider import LLMError

from .aisuite_client import get_aisuite_agent_client
from .config import (
    AGENT_TEMPERATURE,
    AGENT_TOOL_MAX_TURNS,
    get_benchmark_models,
    get_default_agent_model,
)
from .errors import AgentConfigError, AgentExecutionError, AgentRequestError
from .prompt import build_agent_prompt
from .reasoning_tools import build_reasoning_tools
from .traces import serialize_step_trace
from .validation import normalize_agent_action


def plan_next_action(
    snapshot: dict[str, Any], history: list[dict[str, Any]], options: dict[str, Any]
) -> dict[str, Any]:
    client = get_aisuite_agent_client()
    requested_model = resolve_requested_model(client, options)
    run_mode = options.get("runMode", "single")

    if run_mode == "benchmark":
        return run_benchmark(snapshot, history, options, requested_model, client)
    return run_single(snapshot, history, run_mode, requested_model, client)


def resolve_requested_model(client, options: dict[str, Any]) -> str:
    requested = options.get("model")
    if requested:
        return client.resolve_model_name(requested, source="request")

    default_model = get_default_agent_model()
    if not default_model:
        raise AgentConfigError("AGENT_DEFAULT_MODEL or OPENAI_MODEL must be configured")
    return client.resolve_model_name(default_model, source="config")


def run_single(snapshot, history, run_mode, requested_model, client) -> dict[str, Any]:
    result = run_model_turn(client, requested_model, snapshot, history)
    result["trace"] = serialize_step_trace(
        snapshot=snapshot,
        history=history,
        run_mode=run_mode,
        requested_model=requested_model,
        selected_model=requested_model,
        action=result["action"],
        planner=result["planner"],
        response=result["response"],
        benchmark=None,
    )
    return result


def run_benchmark(snapshot, history, options, requested_model, client) -> dict[str, Any]:
    candidate_models = [requested_model]
    candidate_models.extend(
        dedupe_models(options.get("benchmarkModels", []), source="request", include_existing=candidate_models)
    )
    candidate_models.extend(
        dedupe_models(get_benchmark_models(), source="config", include_existing=candidate_models)
    )
    candidates = []
    candidate_results = {}
    selected = None

    for model in candidate_models:
        try:
            candidate = run_model_turn(client, model, snapshot, history)
            candidate_results[model] = candidate
            summary = {
                "model": model,
                "valid": True,
                "action": candidate["action"],
                "planner": candidate["planner"],
            }
            candidates.append(summary)
            if model == requested_model:
                selected = candidate
        except Exception as exc:  # noqa: BLE001
            candidates.append({"model": model, "valid": False, "error": str(exc)})

    if selected is None:
        for candidate in candidates:
            if candidate.get("valid"):
                selected = candidate_results[candidate["model"]]
                break

    if selected is None:
        raise AgentExecutionError("benchmark run did not produce a valid action")

    benchmark = {
        "mode": "benchmark",
        "primaryModel": requested_model,
        "chosenModel": selected["planner"]["model"],
        "candidates": candidates,
    }
    selected["benchmark"] = benchmark
    selected["trace"] = serialize_step_trace(
        snapshot=snapshot,
        history=history,
        run_mode="benchmark",
        requested_model=requested_model,
        selected_model=selected["planner"]["model"],
        action=selected["action"],
        planner=selected["planner"],
        response=selected["response"],
        benchmark=benchmark,
    )
    return selected


def run_model_turn(client, model: str, snapshot: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": (
                "You are a Lode Runner planning agent. Use the helper tools when useful. "
                "Your final answer must be JSON only."
            ),
        },
        {"role": "user", "content": build_agent_prompt(snapshot, history)},
    ]
    tools = build_reasoning_tools(snapshot, history)

    try:
        response = client.create_completion(
            model,
            messages,
            tools=tools,
            max_turns=AGENT_TOOL_MAX_TURNS,
            temperature=AGENT_TEMPERATURE,
        )
    except ValueError as exc:
        raise AgentConfigError(str(exc)) from exc
    except LLMError as exc:
        message = str(exc)
        if "API key" in message or "Provider" in message:
            raise AgentConfigError(message) from exc
        raise AgentExecutionError(message) from exc
    except Exception as exc:  # noqa: BLE001
        raise AgentExecutionError(str(exc)) from exc

    action = parse_action_response(response)
    provider, _model_name = model.split(":", 1)
    planner = {
        "provider": provider,
        "model": model,
        "generatedAt": response.created if hasattr(response, "created") else None,
        "responseId": getattr(response, "id", None),
        "intermediateMessageCount": len(
            getattr(response.choices[0], "intermediate_messages", []) or []
        )
        if getattr(response, "choices", None)
        else 0,
        "reasoningContent": getattr(
            getattr(response.choices[0], "message", None), "reasoning_content", None
        )
        if getattr(response, "choices", None)
        else None,
    }
    return {"action": action, "planner": planner, "response": response}


def parse_action_response(response: Any) -> dict[str, Any]:
    if not getattr(response, "choices", None):
        raise AgentExecutionError("model returned no choices")
    content = getattr(response.choices[0].message, "content", None)
    if not isinstance(content, str) or not content.strip():
        raise AgentExecutionError("model returned no text content")

    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        lines = text.splitlines()
        if lines and lines[0].lower().startswith("json"):
            lines = lines[1:]
        text = "\n".join(lines).strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AgentExecutionError(f"model returned non-JSON action: {exc}") from exc
    try:
        return normalize_agent_action(payload)
    except ValueError as exc:
        raise AgentExecutionError(str(exc)) from exc


def dedupe_models(models: list[str], *, source: str, include_existing: list[str] | None = None) -> list[str]:
    seen = set(include_existing or [])
    deduped = []
    client = get_aisuite_agent_client()
    for model in models:
        normalized = client.resolve_model_name(model, source=source)
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped
