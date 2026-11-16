from __future__ import annotations

import logging
import time
from typing import Any

from .candidates import generate_candidates, is_action_guard_safe, is_action_physically_valid
from .config import (
    AGENT_LEVEL,
    AGENT_PLAY_DATA,
    ResolvedAgentModel,
    get_default_model_profile_name,
    get_default_agent_model,
    load_public_agent_config,
    reload_dotenv_files,
)
from .debug_io import append_model_io_debug
from .errors import AgentConfigError, AgentExecutionError, AgentRequestError
from .llm_client import (
    get_agent_client,
    normalize_chat_response,
    normalize_decision_response,
    parse_chat_response,
    parse_decision_response,
)
from .logging_utils import get_logger, log_event, refresh_app_log_level
from .prompt import build_agent_prompt, build_recent_progress
from .traces import serialize_step_trace


LOGGER = get_logger("service")


def validate_agent_request(payload: Any) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(payload, dict):
        raise AgentRequestError("request body must be an object")
    try:
        play_data = int(payload.get("playData", 0))
        level = int(payload.get("level", 0))
    except (TypeError, ValueError) as exc:
        raise AgentRequestError("playData and level must be integers") from exc
    if play_data != AGENT_PLAY_DATA or level != AGENT_LEVEL:
        raise AgentRequestError("unsupported game context")

    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict):
        raise AgentRequestError("snapshot must be an object")

    history = payload.get("history", [])
    if not isinstance(history, list):
        raise AgentRequestError("history must be an array")

    options = {}
    for field in ("model", "modelProfile", "runId"):
        value = payload.get(field)
        if value is not None and not isinstance(value, str):
            raise AgentRequestError(f"{field} must be a string")
        options[field] = value
    return snapshot, history, options


def plan_next_action(
    snapshot: dict[str, Any], history: list[dict[str, Any]], options: dict[str, Any]
) -> dict[str, Any]:
    reload_dotenv_files()
    refresh_app_log_level()
    public_config = load_public_agent_config()
    client = get_agent_client()
    requested_model = resolve_requested_model(client, options, public_config)
    if options.get("traceGuard"):
        options["traceGuard"](
            {"profile": requested_model.profile, "provider": requested_model.provider,
             "modelId": requested_model.transport_model,
             "api": "decisions" if requested_model.profile == "openai-decisions" else "chat_completions"},
            public_config["backend"],
        )
    if options.get("measurement"):
        options["measurement"].configure(requested_model)
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
    selection_started = time.monotonic()
    log_event(LOGGER, logging.DEBUG, "candidate_selection_start", run_id=options.get("runId"))
    backend_config = public_config["backend"]
    candidates, analysis = generate_candidates(
        snapshot,
        history,
        limit=backend_config["candidateLimit"],
        max_action_ticks=backend_config["maxActionTicks"],
    )
    if not candidates:
        raise AgentExecutionError("candidate generator produced no valid actions")

    if len(candidates) == 1:
        result = {"choice": {"candidateId": candidates[0]["id"]}, "backendForced": True}
    else:
        result = run_model_turn(
            client,
            requested_model,
            snapshot,
            candidates,
            analysis,
            options,
            public_config,
            history=history,
        )
    log_event(
        LOGGER,
        logging.DEBUG,
        "candidate_selection_model_returned",
        run_id=options.get("runId"),
        elapsed_ms=round((time.monotonic() - selection_started) * 1000),
    )
    selected, validation = validate_or_fallback_candidate(result, candidates, analysis, snapshot=snapshot)
    loop_monitor = build_loop_monitor(analysis)

    action = dict(selected["action"])
    action["reason"] = next(iter(selected.get("reasons") or []), "")
    planner = build_planner(
        result, requested_model, validation, public_config, len(candidates)
    )

    trace = serialize_step_trace(
        snapshot=snapshot,
        action=action,
        candidates=candidates,
        selected_candidate=selected,
        validation=validation,
        loop_monitor=loop_monitor,
        analysis=analysis,
        model_selection=build_model_selection_trace(result),
    )
    if isinstance(history, list) and history:
        trace["recentProgress"] = build_recent_progress(history)
    return {
        "action": action,
        "planner": planner,
        "trace": trace,
        "candidateId": selected["id"],
    }


def run_model_turn(
    client,
    model: ResolvedAgentModel,
    snapshot: dict[str, Any],
    candidates: list[dict[str, Any]],
    analysis: dict[str, Any],
    options: dict[str, Any],
    public_config: dict[str, Any],
    *,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    prompt = build_agent_prompt(
        snapshot,
        candidates=candidates,
        analysis=analysis,
        include_reasoning=model.profile == "openai",
        typed_choice=model.profile == "openai-decisions",
        history=history,
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You are a Lode Runner strategic selector. The backend supplies legal candidates. "
                "Choose one candidateId and return JSON only, including a brief rationale when requested."
            ),
        },
        {
            "role": "user",
            "content": prompt,
        },
    ]

    measurement = options.get("measurement")
    if measurement:
        measurement.request_start()
    completion_started = time.monotonic()
    log_event(LOGGER, logging.DEBUG, "chat_completion_start", model=model.model)
    try:
        kwargs = {"temperature": public_config["backend"]["temperature"]}
        if model.profile == "openai-decisions":
            kwargs["candidate_ids"] = [candidate["id"] for candidate in candidates]
        response = client.create_completion(model, messages, **kwargs)
        log_event(
            LOGGER,
            logging.DEBUG,
            "chat_completion_returned",
            model=model.model,
            elapsed_ms=round((time.monotonic() - completion_started) * 1000),
        )
    except Exception as exc:  # noqa: BLE001
        if measurement:
            measurement.request_end()
        # Provider exception text may contain request headers or credentials.
        raise AgentExecutionError(f"model request failed ({type(exc).__name__})") from exc

    elapsed_ms = (time.monotonic() - completion_started) * 1000
    if model.profile == "openai-decisions":
        choice, parse_error = parse_decision_response(response)
        provider_metadata = normalize_decision_response(
            response, model, elapsed_ms, parse_error, [c["id"] for c in candidates]
        )
    else:
        choice, parse_error = parse_chat_response(response)
        provider_metadata = normalize_chat_response(response, model, elapsed_ms, parse_error)
    if measurement:
        measurement.request_end(provider_metadata)
    try:
        append_model_io_debug(
            trace_id=options.get("runId"),
            model=model.transport_model,
            model_profile=model.profile,
            prompt=prompt,
            response=response,
        )
    except Exception as exc:  # noqa: BLE001
        log_event(LOGGER, logging.WARNING, "agent_debug_io_write_failed", error=exc)
    return {
        "choice": choice,
        "parseError": parse_error,
        "diagnostics": provider_metadata.get("diagnostics"),
        "response": response,
    }


def validate_or_fallback_candidate(
    result: dict[str, Any],
    candidates: list[dict[str, Any]],
    analysis: dict[str, Any],
    *,
    snapshot: dict[str, Any] | None = None,
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
        selected["action"],
        analysis["movement"],
        analysis["dig"],
        candidate_kind=selected.get("kind"),
        runner_x_offset=(analysis.get("runner") or {}).get("xOffset"),
    )
    action_guard_safe = is_action_guard_safe(
        selected["action"], analysis, candidate_kind=selected.get("kind"), snapshot=snapshot
    )
    if not action_valid or not action_guard_safe:
        replacement_reason = (
            "selected candidate action was no longer physically valid"
            if not action_valid
            else "selected candidate action moved toward guard pressure"
        )
        selected = candidates[0]
        fallback_used = True
        fallback_reason = replacement_reason
    validation = {
        "requestedCandidateId": requested_id,
        "selectedCandidateId": selected["id"],
        "knownCandidate": requested_id in by_id,
        "fallbackUsed": fallback_used,
        "fallbackReason": fallback_reason,
    }
    return selected, validation


def build_loop_monitor(analysis: dict[str, Any]) -> dict[str, Any]:
    report = analysis.get("loopReport") or {}
    return {
        "active": bool(report.get("active")),
        "type": report.get("type"),
        "evidence": report.get("evidence", {}),
        "suppressedCandidates": report.get("suppressedCandidates", []),
    }


def build_model_selection_trace(result: dict[str, Any]) -> dict[str, Any]:
    choice = result.get("choice") or {}
    return {
        "requestedCandidateId": None if result.get("backendForced") else choice.get("candidateId"),
        "declaredRationale": choice.get("reasoning", "")[:240],
    }


def build_planner(
    result: dict[str, Any],
    model: ResolvedAgentModel,
    validation: dict[str, Any],
    public_config: dict[str, Any],
    candidate_count: int,
) -> dict[str, Any]:
    response = result.get("response")
    return {
        "profile": model.profile,
        "provider": model.provider,
        "modelId": model.transport_model,
        "api": "decisions" if model.profile == "openai-decisions" else "chat_completions",
        "modelSource": model.source,
        "mode": "backend-forced" if result.get("backendForced") else "candidate-selection",
        "generatedAt": getattr(response, "created", None),
        "responseId": getattr(response, "id", None),
        "fallbackUsed": validation["fallbackUsed"],
        "fallbackReason": validation["fallbackReason"],
        "candidateCount": candidate_count,
        **({"diagnostics": result["diagnostics"]} if result.get("diagnostics") else {}),
        "config": {
            "candidateLimit": public_config["backend"]["candidateLimit"],
            "maxActionTicks": public_config["backend"]["maxActionTicks"],
            "temperature": public_config["backend"]["temperature"],
        },
    }
