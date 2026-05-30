from __future__ import annotations

import json
import logging
from typing import Any

import aisuite as ai
from aisuite.provider import LLMError
from aisuite.provider import ProviderFactory

from .candidates import generate_candidates, is_action_physically_valid
from .config import (
    AGENT_LEVEL,
    AGENT_PLAY_DATA,
    ResolvedAgentModel,
    get_default_model_profile_name,
    get_default_agent_model,
    get_explicit_provider_configs,
    load_public_agent_config,
    normalize_model_name,
    reload_dotenv_files,
    resolve_model_profile,
)
from .debug_io import append_model_io_debug
from .errors import AgentConfigError, AgentExecutionError, AgentRequestError
from .logging_utils import get_logger, log_event, refresh_app_log_level
from .prompt import build_agent_prompt
from .stall_tools import is_candidate_blocked
from .traces import serialize_step_trace


LOGGER = get_logger("service")


class AisuiteAgentClient:
    def __init__(self) -> None:
        self._clients: dict[str, ai.Client] = {}

    def resolve_model_name(self, model: str | None, *, source: str) -> ResolvedAgentModel:
        error_cls = AgentRequestError if source == "request" else AgentConfigError
        try:
            normalized = normalize_model_name(model, require_provider=True)
        except ValueError as exc:
            raise error_cls(str(exc)) from exc
        if not normalized:
            raise error_cls("agent model is required")

        provider_key, _model_name = normalized.split(":", 1)
        supported = ProviderFactory.get_supported_providers()
        if provider_key not in supported:
            error_cls = AgentRequestError if source == "request" else AgentConfigError
            raise error_cls(
                f"unsupported provider '{provider_key}'. Supported providers: {sorted(supported)}"
            )
        return ResolvedAgentModel(
            profile="explicit",
            provider=provider_key,
            model=normalized,
            aisuite_provider=provider_key,
            aisuite_model=normalized,
            provider_configs=get_explicit_provider_configs(provider_key),
            source=source,
        )

    def resolve_model_profile(self, profile: str | None, *, source: str) -> ResolvedAgentModel:
        error_cls = AgentRequestError if source == "request" else AgentConfigError
        try:
            resolved = resolve_model_profile(profile, source=source)
        except ValueError as exc:
            raise error_cls(str(exc)) from exc
        if resolved is None:
            raise error_cls("modelProfile is required")

        supported = ProviderFactory.get_supported_providers()
        if resolved.aisuite_provider not in supported:
            raise error_cls(
                f"unsupported provider '{resolved.aisuite_provider}' for profile "
                f"'{resolved.profile}'. Supported providers: {sorted(supported)}"
            )
        return resolved

    def create_completion(self, model: ResolvedAgentModel, messages: list[dict], **kwargs):
        client = self._get_client(model.provider_configs)
        return client.chat.completions.create(
            model=model.aisuite_model,
            messages=messages,
            **kwargs,
        )

    def _get_client(self, provider_configs: dict[str, dict[str, Any]]):
        cache_key = json.dumps(provider_configs, sort_keys=True)
        if cache_key not in self._clients:
            self._clients[cache_key] = ai.Client(provider_configs=provider_configs)
        return self._clients[cache_key]


_CLIENT: AisuiteAgentClient | None = None


def get_aisuite_agent_client() -> AisuiteAgentClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = AisuiteAgentClient()
    return _CLIENT


def validate_agent_request(payload: Any) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(payload, dict):
        raise AgentRequestError("request body must be an object")
    try:
        play_data = int(payload.get("playData", 0))
        level = int(payload.get("level", 0))
    except (TypeError, ValueError) as exc:
        raise AgentRequestError("playData and level must be integers") from exc
    if play_data != AGENT_PLAY_DATA or level != AGENT_LEVEL:
        raise AgentRequestError("only Classic level 1 is supported")

    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict):
        raise AgentRequestError("snapshot must be an object")

    history = payload.get("history", [])
    if not isinstance(history, list):
        raise AgentRequestError("history must be an array")

    model = payload.get("model")
    if model is not None and not isinstance(model, str):
        raise AgentRequestError("model must be a string")

    model_profile = payload.get("modelProfile")
    if model_profile is not None and not isinstance(model_profile, str):
        raise AgentRequestError("modelProfile must be a string")

    run_id = payload.get("runId")
    if run_id is not None and not isinstance(run_id, str):
        raise AgentRequestError("runId must be a string")

    return snapshot, history, {
        "model": model,
        "modelProfile": model_profile,
        "runId": run_id,
    }


def plan_next_action(
    snapshot: dict[str, Any], history: list[dict[str, Any]], options: dict[str, Any]
) -> dict[str, Any]:
    reload_dotenv_files()
    refresh_app_log_level()
    public_config = load_public_agent_config()
    client = get_aisuite_agent_client()
    requested_model = resolve_requested_model(client, options, public_config)
    return run_candidate_selection(snapshot, history, requested_model, client, options, public_config)


def resolve_requested_model(
    client,
    options: dict[str, Any],
    public_config: dict[str, Any],
) -> ResolvedAgentModel:
    requested = options.get("model")
    if requested:
        return client.resolve_model_name(requested, source="request")

    requested_profile = options.get("modelProfile")
    if requested_profile:
        return client.resolve_model_profile(requested_profile, source="request")

    config_profile = (public_config.get("agent") or {}).get("modelProfile")
    if config_profile:
        return client.resolve_model_profile(config_profile, source="config")

    default_profile = get_default_model_profile_name()
    if default_profile:
        return client.resolve_model_profile(default_profile, source="config")

    default_model = get_default_agent_model()
    if not default_model:
        raise AgentConfigError(
            "AGENT_MODEL_PROFILE or AGENT_DEFAULT_MODEL must be configured"
        )
    return client.resolve_model_name(default_model, source="config")


def run_candidate_selection(
    snapshot: dict[str, Any],
    history: list[dict[str, Any]],
    requested_model: ResolvedAgentModel,
    client,
    options: dict[str, Any],
    public_config: dict[str, Any],
) -> dict[str, Any]:
    backend_config = public_config["backend"]
    candidates, analysis = generate_candidates(
        snapshot,
        history,
        limit=backend_config["candidateLimit"],
        max_action_ticks=backend_config["maxActionTicks"],
    )
    if not candidates:
        raise AgentExecutionError("candidate generator produced no valid actions")

    result = run_model_turn(
        client,
        requested_model,
        snapshot,
        history,
        candidates,
        analysis,
        options,
        public_config,
    )
    selected, validation = validate_or_fallback_candidate(result, candidates, analysis)
    stall_supervisor = build_stall_supervisor(validation, analysis)
    if validation.get("stallBlocked"):
        retry_note = (
            "The previous candidate repeats a detected stall. "
            "Choose a non-blocked recovery candidate from the list. "
            f"Stall reason: {validation.get('stallBlockReason')}. "
            f"Preferred recovery kinds: {analysis.get('stallReport', {}).get('preferredCandidateKinds', [])}."
        )
        retry_result = run_model_turn(
            client,
            requested_model,
            snapshot,
            history,
            candidates,
            analysis,
            options,
            public_config,
            retry_note=retry_note,
        )
        retry_selected, retry_validation = validate_or_fallback_candidate(
            retry_result, candidates, analysis
        )
        stall_supervisor.update(
            {
                "retryAttempted": True,
                "retryRequestedCandidateId": retry_validation.get("requestedCandidateId"),
                "retrySelectedCandidateId": retry_validation.get("selectedCandidateId"),
                "retryStallBlocked": retry_validation.get("stallBlocked"),
            }
        )
        result = retry_result
        selected = retry_selected
        validation = retry_validation
        if validation.get("stallBlocked"):
            fallback = first_nonblocked_valid_candidate(candidates, analysis)
            if fallback is None:
                raise AgentExecutionError("agent stalled: no recovery candidate is available")
            stall_supervisor.update(
                {
                    "fallbackAfterRetry": True,
                    "fallbackCandidateId": fallback["id"],
                    "fallbackReason": validation.get("stallBlockReason"),
                }
            )
            selected = fallback
            validation = {
                **validation,
                "selectedCandidateId": selected["id"],
                "fallbackUsed": True,
                "fallbackReason": "stall supervisor fallback after blocked retry",
                "stallBlocked": False,
                "stallBlockReason": None,
            }

    action = dict(selected["firstAction"])
    planner = build_planner(result, requested_model, validation, public_config)
    planner["candidateCount"] = len(candidates)

    trace = serialize_step_trace(
        snapshot=snapshot,
        history=history,
        action=action,
        candidates=candidates,
        selected_candidate=selected,
        validation=validation,
        stall_supervisor=stall_supervisor,
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
    model: ResolvedAgentModel,
    snapshot: dict[str, Any],
    history: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    analysis: dict[str, Any],
    options: dict[str, Any],
    public_config: dict[str, Any],
    retry_note: str | None = None,
) -> dict[str, Any]:
    prompt = build_agent_prompt(
        snapshot,
        history,
        candidates=candidates,
        analysis=analysis,
        retry_note=retry_note,
        show_candidate_scores=public_config["prompt"]["showCandidateScores"],
    )
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
            "content": prompt,
        },
    ]

    try:
        response = client.create_completion(
            model,
            messages,
            temperature=public_config["backend"]["temperature"],
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
    try:
        append_model_io_debug(
            trace_id=options.get("runId"),
            model=model.model,
            retry=retry_note is not None,
            prompt=prompt,
            response=response,
            parse_error=parse_error,
            selected_candidate_id=(choice or {}).get("candidateId"),
        )
    except Exception as exc:  # noqa: BLE001
        log_event(LOGGER, logging.WARNING, "agent_debug_io_write_failed", error=exc)
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
        selected = first_nonblocked_valid_candidate(candidates, analysis) or candidates[0]
        fallback_used = True
        fallback_reason = result.get("parseError") or f"unknown candidateId: {requested_id}"

    action_valid = is_action_physically_valid(
        selected["firstAction"],
        analysis["movement"],
        analysis["dig"],
    )
    if not action_valid:
        valid_candidate = first_nonblocked_valid_candidate(candidates, analysis)
        if valid_candidate is None:
            raise AgentExecutionError("selected candidate action is no longer physically valid")
        selected = valid_candidate
        action_valid = True
        fallback_used = True
        fallback_reason = "selected candidate action was no longer physically valid"
    stall_blocked, stall_block_reason = is_candidate_blocked(
        selected, analysis.get("stallReport") or analysis.get("progressMonitor") or {}
    )

    validation = {
        "requestedCandidateId": requested_id,
        "selectedCandidateId": selected["id"],
        "knownCandidate": requested_id in by_id,
        "fallbackUsed": fallback_used,
        "fallbackReason": fallback_reason,
        "actionValid": action_valid,
        "stallBlocked": stall_blocked,
        "stallBlockReason": stall_block_reason,
        "stallReportType": (analysis.get("stallReport") or {}).get("type"),
        "stallSeverity": (analysis.get("stallReport") or {}).get("severity"),
        "choiceReason": choice.get("reason"),
    }
    return selected, validation


def first_nonblocked_valid_candidate(
    candidates: list[dict[str, Any]], analysis: dict[str, Any]
) -> dict[str, Any] | None:
    stall_report = analysis.get("stallReport") or analysis.get("progressMonitor") or {}
    for candidate in candidates:
        if not is_action_physically_valid(candidate["firstAction"], analysis["movement"], analysis["dig"]):
            continue
        blocked, _reason = is_candidate_blocked(candidate, stall_report)
        if not blocked:
            return candidate
    return None


def build_stall_supervisor(validation: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    stall_report = analysis.get("stallReport") or analysis.get("progressMonitor") or {}
    return {
        "enabled": True,
        "severity": stall_report.get("severity"),
        "type": stall_report.get("type"),
        "stalled": bool(stall_report.get("stalled")),
        "blockedCandidateIds": stall_report.get("blockedCandidateIds", []),
        "blockedCandidateKinds": stall_report.get("blockedCandidateKinds", []),
        "preferredCandidateKinds": stall_report.get("preferredCandidateKinds", []),
        "initialRequestedCandidateId": validation.get("requestedCandidateId"),
        "initialSelectedCandidateId": validation.get("selectedCandidateId"),
        "initialStallBlocked": validation.get("stallBlocked"),
        "initialStallBlockReason": validation.get("stallBlockReason"),
        "retryAttempted": False,
        "fallbackAfterRetry": False,
    }


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
    model: ResolvedAgentModel,
    validation: dict[str, Any],
    public_config: dict[str, Any],
) -> dict[str, Any]:
    response = result.get("response")
    return {
        "modelProfile": model.profile,
        "provider": model.provider,
        "model": model.model,
        "modelSource": model.source,
        "mode": "candidate-selection",
        "generatedAt": getattr(response, "created", None),
        "responseId": getattr(response, "id", None),
        "fallbackUsed": validation["fallbackUsed"],
        "fallbackReason": validation["fallbackReason"],
        "candidateCount": None,
        "config": {
            "showCandidateScores": public_config["prompt"]["showCandidateScores"],
            "candidateLimit": public_config["backend"]["candidateLimit"],
            "maxActionTicks": public_config["backend"]["maxActionTicks"],
            "temperature": public_config["backend"]["temperature"],
        },
    }


def summarize_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": candidate["id"],
            "kind": candidate["kind"],
            "score": candidate["score"],
            "baseScore": candidate.get("baseScore"),
            "stallBlocked": candidate.get("stallBlocked", False),
            "stallRecovery": candidate.get("stallRecovery", False),
            "target": candidate.get("target"),
            "firstAction": candidate.get("firstAction"),
            "goal": candidate.get("goal"),
        }
        for candidate in candidates
    ]
