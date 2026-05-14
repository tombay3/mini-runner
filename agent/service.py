from __future__ import annotations

import json
from typing import Any

from aisuite.provider import LLMError

from .aisuite_client import get_aisuite_agent_client
from .candidates import generate_candidates, is_action_physically_valid
from .config import AGENT_TEMPERATURE, get_default_agent_model
from .errors import AgentConfigError, AgentExecutionError
from .prompt import build_agent_prompt
from .traces import serialize_step_trace


def plan_next_action(
    snapshot: dict[str, Any], history: list[dict[str, Any]], options: dict[str, Any]
) -> dict[str, Any]:
    client = get_aisuite_agent_client()
    requested_model = resolve_requested_model(client, options)
    run_mode = options.get("runMode", "single")
    return run_candidate_selection(snapshot, history, run_mode, requested_model, client)


def resolve_requested_model(client, options: dict[str, Any]) -> str:
    requested = options.get("model")
    if requested:
        return client.resolve_model_name(requested, source="request")

    default_model = get_default_agent_model()
    if not default_model:
        raise AgentConfigError("AGENT_DEFAULT_MODEL or OPENAI_MODEL must be configured")
    return client.resolve_model_name(default_model, source="config")


def run_candidate_selection(
    snapshot: dict[str, Any],
    history: list[dict[str, Any]],
    run_mode: str,
    requested_model: str,
    client,
) -> dict[str, Any]:
    candidates, analysis = generate_candidates(snapshot, history, limit=7)
    if not candidates:
        raise AgentExecutionError("candidate generator produced no valid actions")

    result = run_model_turn(client, requested_model, snapshot, history, candidates, analysis)
    selected, validation = validate_or_fallback_candidate(result, candidates, analysis)
    action = dict(selected["firstAction"])
    planner = build_planner(result, requested_model, selected, validation)
    planner["candidateCount"] = len(candidates)

    trace = serialize_step_trace(
        snapshot=snapshot,
        history=history,
        run_mode=run_mode,
        requested_model=requested_model,
        selected_model=requested_model,
        action=action,
        planner=planner,
        response=result.get("response"),
        guardrail=None,
        candidates=candidates,
        selected_candidate=selected,
        validation=validation,
        analysis=analysis,
    )
    return {
        "action": action,
        "planner": planner,
        "trace": trace,
        "candidateId": selected["id"],
        "candidate": selected,
        "candidates": summarize_candidates(candidates),
        "validation": validation,
    }


def run_model_turn(
    client,
    model: str,
    snapshot: dict[str, Any],
    history: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": (
                "You are a Lode Runner strategic selector. The backend supplies legal candidates. "
                "Choose one candidateId and return JSON only."
            ),
        },
        {
            "role": "user",
            "content": build_agent_prompt(
                snapshot,
                history,
                candidates=candidates,
                analysis=analysis,
            ),
        },
    ]

    try:
        response = client.create_completion(
            model,
            messages,
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

    choice, parse_error = parse_candidate_response(response)
    return {
        "choice": choice,
        "parseError": parse_error,
        "response": response,
    }


def validate_or_fallback_candidate(
    result: dict[str, Any],
    candidates: list[dict[str, Any]],
    analysis: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    by_id = {candidate["id"]: candidate for candidate in candidates}
    choice = result.get("choice") or {}
    requested_id = choice.get("candidateId")
    selected = by_id.get(requested_id)
    fallback_used = False
    fallback_reason = None

    if selected is None:
        selected = candidates[0]
        fallback_used = True
        fallback_reason = result.get("parseError") or f"unknown candidateId: {requested_id}"

    action_valid = is_action_physically_valid(
        selected["firstAction"],
        analysis["movement"],
        analysis["dig"],
    )
    if not action_valid:
        valid_candidates = [
            candidate
            for candidate in candidates
            if is_action_physically_valid(candidate["firstAction"], analysis["movement"], analysis["dig"])
        ]
        if not valid_candidates:
            raise AgentExecutionError("selected candidate action is no longer physically valid")
        selected = valid_candidates[0]
        fallback_used = True
        fallback_reason = "selected candidate action was no longer physically valid"

    validation = {
        "requestedCandidateId": requested_id,
        "selectedCandidateId": selected["id"],
        "knownCandidate": requested_id in by_id,
        "fallbackUsed": fallback_used,
        "fallbackReason": fallback_reason,
        "actionValid": action_valid,
        "choiceReason": choice.get("reason"),
    }
    return selected, validation


def parse_candidate_response(response: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not getattr(response, "choices", None):
        return None, "model returned no choices"
    message = getattr(response.choices[0], "message", None)
    content = getattr(message, "content", None)
    if not isinstance(content, str) or not content.strip():
        return None, "model returned no text content"

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
        return None, f"model returned non-JSON candidate choice: {exc}"
    if not isinstance(payload, dict):
        return None, "model candidate choice must be an object"

    candidate_id = payload.get("candidateId")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        return None, "candidateId must be a non-empty string"
    return {
        "candidateId": candidate_id.strip(),
        "reason": str(payload.get("reason", ""))[:500],
    }, None


def build_planner(
    result: dict[str, Any],
    model: str,
    selected: dict[str, Any],
    validation: dict[str, Any],
) -> dict[str, Any]:
    provider, _model_name = model.split(":", 1)
    response = result.get("response")
    choices = getattr(response, "choices", None)
    message = getattr(choices[0], "message", None) if choices else None
    return {
        "provider": provider,
        "model": model,
        "mode": "candidate-selection",
        "generatedAt": getattr(response, "created", None),
        "responseId": getattr(response, "id", None),
        "reasoningContent": getattr(message, "reasoning_content", None),
        "selectedCandidateId": selected["id"],
        "selectedCandidateKind": selected["kind"],
        "fallbackUsed": validation["fallbackUsed"],
        "fallbackReason": validation["fallbackReason"],
        "candidateCount": None,
    }


def summarize_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": candidate["id"],
            "kind": candidate["kind"],
            "score": candidate["score"],
            "target": candidate.get("target"),
            "firstAction": candidate.get("firstAction"),
            "goal": candidate.get("goal"),
        }
        for candidate in candidates
    ]
