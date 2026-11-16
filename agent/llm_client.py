"""Model resolution, API requests and response parsing for the gameplay planner."""
import json
import math
from typing import Any

import openai

from .config import ResolvedAgentModel, get_explicit_provider_configs, normalize_model_name, resolve_model_profile
from .errors import AgentConfigError, AgentRequestError


class AgentClient:
    def __init__(self):
        self._clients = {}

    def resolve_model_name(self, model, *, source):
        error = AgentRequestError if source == "request" else AgentConfigError
        try:
            normalized = normalize_model_name(model, require_provider=True)
        except ValueError as exc:
            raise error(str(exc)) from exc
        if not normalized:
            raise error("agent model is required")
        provider, name = normalized.split(":", 1)
        if provider == "minimax":
            raise error("MiniMax direct access is retired; choose an OpenAI or Gemini profile explicitly")
        if provider != "openai" or not name:
            raise error(f"unsupported explicit provider '{provider}'; use openai:model or a supported profile")
        return ResolvedAgentModel("explicit", provider, normalized, name,
                                  get_explicit_provider_configs(provider), source)

    def resolve_model_profile(self, profile, *, source):
        error = AgentRequestError if source == "request" else AgentConfigError
        try:
            result = resolve_model_profile(profile, source=source)
        except ValueError as exc:
            raise error(str(exc)) from exc
        if result is None:
            raise error("modelProfile is required")
        return result

    def create_completion(self, model, messages, **kwargs):
        config = model.provider_configs.get("openai", {})
        key = json.dumps(config, sort_keys=True)
        if key not in self._clients:
            self._clients[key] = openai.OpenAI(**config, timeout=90.0, max_retries=0)
        client = self._clients[key]
        if model.profile == "openai-decisions":
            return client.decisions.create(
                model=model.transport_model,
                input=messages[-1]["content"],
                questions=[{
                    "type": "choice",
                    "name": "candidate",
                    "instructions": "Select the best supplied candidate ID.",
                    "choices": [{"value": item} for item in kwargs["candidate_ids"]],
                }],
            )

        kwargs.pop("candidate_ids", None)
        settings = effective_settings(model, kwargs)
        if model.profile == "openrouter":
            settings["extra_body"] = {"provider": {
                "only": [model.routing_provider],
                "allow_fallbacks": False,
                "require_parameters": True,
            }}
        return client.chat.completions.create(model=model.transport_model, messages=messages, **settings)


_CLIENT = None


def get_agent_client():
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = AgentClient()
    return _CLIENT


def effective_settings(model, settings):
    settings = dict(settings)
    # GPT-5 reasoning models do not generally accept temperature.
    if model.provider == "openai" and model.transport_model.lower().startswith("gpt-5"):
        settings.pop("temperature", None)
    return settings


def configured_gateway(model):
    base_url = model.provider_configs.get("openai", {}).get("base_url")
    expected_base = "https://generativelanguage.googleapis.com/v1beta/openai/"
    custom_endpoint = bool(base_url and (model.provider != "gemini" or base_url.rstrip("/") != expected_base.rstrip("/")))
    return "openrouter" if model.profile == "openrouter" else ("custom" if custom_endpoint else "direct")


def _response_json_text(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        lines = text.splitlines()
        if lines and lines[0].lower().startswith("json"):
            lines = lines[1:]
        text = "\n".join(lines).strip()
    return text


def parse_chat_response(response: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not getattr(response, "choices", None):
        return None, "model returned no choices"
    message = getattr(response.choices[0], "message", None)
    if getattr(message, "refusal", None):
        return None, "model refused candidate selection"
    content = getattr(message, "content", None)
    if not isinstance(content, str) or not content.strip():
        return None, "model returned no text content"

    text = _response_json_text(content)

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, f"model returned non-JSON candidate choice: {exc}"
    if not isinstance(payload, dict):
        return None, "model candidate choice must be an object"

    candidate_id = payload.get("candidateId")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        return None, "candidateId must be a non-empty string"
    choice = {"candidateId": candidate_id.strip()}
    reasoning = payload.get("reasoning")
    if isinstance(reasoning, str) and reasoning.strip():
        choice["reasoning"] = reasoning.strip()[:1000]
    return choice, None


def normalize_chat_response(response, model, elapsed_ms, parse_error):
    usage = getattr(response, "usage", None)
    details = getattr(usage, "prompt_tokens_details", None)
    output_details = getattr(usage, "completion_tokens_details", None)
    message = response.choices[0].message if getattr(response, "choices", None) else None
    gateway = configured_gateway(model)
    is_router = gateway == "openrouter"
    returned_provider = getattr(response, "provider", None) if is_router else None
    return {
        "resolvedModel": getattr(response, "model", None),
        "gateway": gateway, "servingProvider": returned_provider if is_router else (None if gateway == "custom" else model.provider), "api": "chat_completions",
        "usage": {"inputTokens": getattr(usage, "prompt_tokens", None),
                  "outputTokens": getattr(usage, "completion_tokens", None),
                  "cachedInputTokens": getattr(details, "cached_tokens", None),
                  "cacheWriteTokens": getattr(details, "cache_write_tokens", None),
                  "reasoningTokens": getattr(output_details, "reasoning_tokens", None)},
        "elapsedMs": elapsed_ms,
        "status": "refusal" if getattr(message, "refusal", None) else ("parse_error" if parse_error else "ok"),
    }


def parse_decision_response(response):
    answers = getattr(response, "answers", None) or []
    if len(answers) != 1:
        return None, "model returned an invalid number of answers"
    answer = answers[0]
    if getattr(answer, "type", None) == "refusal":
        return None, "model refused candidate selection"
    value = getattr(answer, "choice", None)
    if getattr(answer, "type", None) != "choice" or not isinstance(value, str) or not value.strip():
        return None, "model returned malformed choice"
    return {"candidateId": value.strip()}, None


def normalize_decision_response(response, model, elapsed_ms, parse_error, candidate_ids=()):
    usage = getattr(response, "usage", None)
    details = getattr(usage, "input_tokens_details", None)
    output = getattr(usage, "output_tokens_details", None)
    custom = bool(model.provider_configs.get("openai", {}).get("base_url"))
    answers = getattr(response, "answers", None) or []
    answer = answers[0] if len(answers) == 1 and getattr(answers[0], "type", None) == "choice" else None
    confidence = getattr(answer, "confidence", None)
    def probability(value):
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value <= 1 else None
    probabilities = []
    for item in getattr(answer, "probabilities", None) or []:
        value, p = getattr(item, "value", None), probability(getattr(item, "probability", None))
        if isinstance(value, str) and value in candidate_ids and p is not None:
            probabilities.append({"candidateId": value, "probability": p})
    return {"diagnostics": {"confidence": probability(confidence), "probabilities": probabilities},
        "resolvedModel": getattr(response, "model", None),
        "gateway": "custom" if custom else "direct", "servingProvider": None if custom else "openai",
        "api": "decisions",
        "usage": {"inputTokens": getattr(usage, "input_tokens", None),
            "outputTokens": getattr(usage, "output_tokens", None),
            "cachedInputTokens": getattr(details, "cached_tokens", None),
            "cacheWriteTokens": getattr(details, "cache_write_tokens", None),
            "reasoningTokens": getattr(output, "reasoning_tokens", None)},
        "elapsedMs": elapsed_ms, "status": "refusal" if parse_error == "model refused candidate selection" else ("parse_error" if parse_error else "ok")}
