from __future__ import annotations

import aisuite as ai
from aisuite.provider import ProviderFactory

from .config import normalize_model_name
from .errors import AgentConfigError, AgentRequestError


class AisuiteAgentClient:
    def __init__(self) -> None:
        self._client = ai.Client()

    def resolve_model_name(self, model: str | None, *, source: str) -> str:
        normalized = normalize_model_name(model)
        if not normalized:
            error_cls = AgentRequestError if source == "request" else AgentConfigError
            raise error_cls("agent model is required")

        provider_key, _model_name = normalized.split(":", 1)
        supported = ProviderFactory.get_supported_providers()
        if provider_key not in supported:
            error_cls = AgentRequestError if source == "request" else AgentConfigError
            raise error_cls(
                f"unsupported provider '{provider_key}'. Supported providers: {sorted(supported)}"
            )
        return normalized

    def create_completion(self, model: str, messages: list[dict], **kwargs):
        return self._client.chat.completions.create(model=model, messages=messages, **kwargs)


_CLIENT: AisuiteAgentClient | None = None


def get_aisuite_agent_client() -> AisuiteAgentClient:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = AisuiteAgentClient()
    return _CLIENT
