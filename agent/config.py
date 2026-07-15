from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
from typing import Any

try:
    from dotenv import dotenv_values
except ImportError:  # pragma: no cover - dependency is declared, fallback keeps imports safe.
    dotenv_values = None


ROOT_DIR = Path(__file__).resolve().parent.parent
LLM_GAME_RULES_PATH = ROOT_DIR / "public" / "LLM_GAME_RULES.md"
AGENT_CONFIG_PATH = ROOT_DIR / "public" / "agent-config.json"
DOTENV_PATHS = (
    Path.home() / ".env",
    ROOT_DIR / ".env",
    Path.home() / ".env.local",
    ROOT_DIR / ".env.local",
)
_DOTENV_MANAGED_KEYS: set[str] = set()
_DOTENV_ORIGINAL_ENV: dict[str, str | None] = {}

AGENT_PLAY_DATA = 1
AGENT_LEVEL = 1
AGENT_MAX_TICKS = 20
AGENT_TEMPERATURE = 0.5
AGENT_MODEL_PROFILES = {"openai", "minimax", "gemini"}
GEMINI_DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

PUBLIC_AGENT_CONFIG_DEFAULTS: dict[str, Any] = {
    "agent": {
        "playData": AGENT_PLAY_DATA,
        "level": AGENT_LEVEL,
        "maxPlaybackTimeSeconds": 120,
        "maxSteps": 200,
        "historyLimit": 24,
        "modelProfile": None,
    },
    "backend": {
        "candidateLimit": 7,
        "maxActionTicks": AGENT_MAX_TICKS,
        "temperature": AGENT_TEMPERATURE,
    },
    "prompt": {
        "showCandidateScores": True,
    },
}


@dataclass(frozen=True)
class ResolvedAgentModel:
    profile: str
    provider: str
    model: str
    aisuite_provider: str
    aisuite_model: str
    provider_configs: dict[str, dict[str, Any]]
    source: str


def reload_dotenv_files() -> list[str]:
    if dotenv_values is None:
        return []

    loaded_paths = []
    merged_values: dict[str, str] = {}
    for path in DOTENV_PATHS:
        if path.exists():
            for key, value in dotenv_values(path).items():
                if value is not None:
                    merged_values[key] = value
            loaded_paths.append(str(path))

    global _DOTENV_MANAGED_KEYS
    for key in _DOTENV_MANAGED_KEYS - set(merged_values):
        original = _DOTENV_ORIGINAL_ENV.get(key)
        if original is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original

    for key, value in merged_values.items():
        if key not in _DOTENV_ORIGINAL_ENV:
            _DOTENV_ORIGINAL_ENV[key] = os.environ.get(key)
        os.environ[key] = value
    _DOTENV_MANAGED_KEYS = set(merged_values)
    return loaded_paths


def load_public_agent_config() -> dict[str, Any]:
    raw: Any = {}
    try:
        parsed = json.loads(AGENT_CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(parsed, dict):
            raw = parsed
    except (OSError, json.JSONDecodeError):
        raw = {}

    agent = _dict(raw.get("agent"))
    backend = _dict(raw.get("backend"))
    prompt = _dict(raw.get("prompt"))
    defaults = PUBLIC_AGENT_CONFIG_DEFAULTS
    return {
        "agent": {
            "playData": _positive_int(agent.get("playData"), defaults["agent"]["playData"]),
            "level": _positive_int(agent.get("level"), defaults["agent"]["level"]),
            "maxPlaybackTimeSeconds": _positive_int(
                agent.get("maxPlaybackTimeSeconds"),
                defaults["agent"]["maxPlaybackTimeSeconds"],
            ),
            "maxSteps": _positive_int(agent.get("maxSteps"), defaults["agent"]["maxSteps"]),
            "historyLimit": _positive_int(
                agent.get("historyLimit"),
                defaults["agent"]["historyLimit"],
            ),
            "modelProfile": _optional_string(agent.get("modelProfile")),
        },
        "backend": {
            "candidateLimit": _positive_int(
                backend.get("candidateLimit"),
                defaults["backend"]["candidateLimit"],
                maximum=20,
            ),
            "maxActionTicks": _positive_int(
                backend.get("maxActionTicks"),
                defaults["backend"]["maxActionTicks"],
                maximum=AGENT_MAX_TICKS,
            ),
            "temperature": _bounded_float(
                backend.get("temperature"),
                defaults["backend"]["temperature"],
                minimum=0.0,
                maximum=2.0,
            ),
        },
        "prompt": {
            "showCandidateScores": _bool_value(
                prompt.get("showCandidateScores"),
                defaults["prompt"]["showCandidateScores"],
            ),
        },
    }


def normalize_model_name(
    model: str | None, default_provider: str | None = None, *, require_provider: bool = False
) -> str | None:
    if model is None:
        return None
    normalized = str(model).strip()
    if not normalized:
        return None
    if ":" not in normalized:
        if require_provider or default_provider is None:
            raise ValueError("model must use provider:model format")
        normalized = f"{default_provider}:{normalized}"
    return normalized


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _positive_int(value: Any, default: int, *, maximum: int | None = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    if result < 1:
        result = default
    if maximum is not None:
        result = min(result, maximum)
    return result


def _bounded_float(value: Any, default: float, *, minimum: float, maximum: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    if not math.isfinite(result):
        result = default
    return max(minimum, min(maximum, result))


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bool_value(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def get_default_agent_model() -> str | None:
    return normalize_model_name(os.environ.get("AGENT_DEFAULT_MODEL"), require_provider=True)


def get_env_value(*names: str) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None


def get_default_model_profile_name() -> str | None:
    value = get_env_value("AGENT_MODEL_PROFILE")
    return value.lower() if value else None


def resolve_model_profile(profile: str | None, *, source: str) -> ResolvedAgentModel | None:
    if profile is None:
        return None
    normalized = str(profile).strip().lower()
    if not normalized:
        return None
    if normalized not in AGENT_MODEL_PROFILES:
        raise ValueError(
            f"unsupported modelProfile '{normalized}'. Supported profiles: {sorted(AGENT_MODEL_PROFILES)}"
        )
    if normalized == "openai":
        return resolve_openai_profile(source=source)
    if normalized == "minimax":
        return resolve_minimax_profile(source=source)
    if normalized == "gemini":
        return resolve_gemini_profile(source=source)
    raise ValueError(f"unsupported modelProfile '{normalized}'")


def resolve_openai_profile(*, source: str) -> ResolvedAgentModel:
    model = normalize_model_name(get_env_value("OPENAI_MODEL"), "openai")
    if not model:
        raise ValueError("OPENAI_MODEL must be configured for openai profile")
    provider, _model_name = model.split(":", 1)
    if provider != "openai":
        raise ValueError("openai profile requires an OpenAI model name")
    api_key = get_env_value("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY must be configured for openai profile")
    provider_config: dict[str, Any] = {"api_key": api_key}
    base_url = get_env_value("OPENAI_BASE_URL")
    if base_url:
        provider_config["base_url"] = base_url
    return ResolvedAgentModel(
        profile="openai",
        provider="openai",
        model=model,
        aisuite_provider="openai",
        aisuite_model=model,
        provider_configs={"openai": provider_config},
        source=source,
    )


def resolve_minimax_profile(*, source: str) -> ResolvedAgentModel:
    model_name = get_env_value("MINIMAX_MODEL")
    if not model_name:
        raise ValueError("MINIMAX_MODEL must be configured for minimax profile")
    api_key = get_env_value("MINIMAX_API_KEY")
    if not api_key:
        raise ValueError("MINIMAX_API_KEY must be configured for minimax profile")
    provider_config: dict[str, Any] = {"api_key": api_key}
    base_url = get_env_value("MINIMAX_BASE_URL", "MINIMAX_API_BASE")
    if base_url:
        provider_config["base_url"] = base_url
    return ResolvedAgentModel(
        profile="minimax",
        provider="minimax",
        model=f"minimax:{model_name}",
        aisuite_provider="minimax",
        aisuite_model=f"minimax:{model_name}",
        provider_configs={"minimax": provider_config},
        source=source,
    )


def resolve_gemini_profile(*, source: str) -> ResolvedAgentModel:
    model_name = get_env_value("GEMINI_MODEL")
    if not model_name:
        raise ValueError("GEMINI_MODEL must be configured for gemini profile")
    api_key = get_env_value("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY must be configured for gemini profile")
    base_url = get_env_value("GEMINI_API_BASE") or GEMINI_DEFAULT_BASE_URL
    provider_config = {"api_key": api_key, "base_url": base_url}
    return ResolvedAgentModel(
        profile="gemini",
        provider="gemini",
        model=f"gemini:{model_name}",
        aisuite_provider="openai",
        aisuite_model=f"openai:{model_name}",
        provider_configs={"openai": provider_config},
        source=source,
    )


def get_explicit_provider_configs(provider: str) -> dict[str, dict[str, Any]]:
    if provider == "openai":
        provider_config: dict[str, Any] = {}
        api_key = get_env_value("OPENAI_API_KEY")
        if api_key:
            provider_config["api_key"] = api_key
        base_url = get_env_value("OPENAI_BASE_URL")
        if base_url:
            provider_config["base_url"] = base_url
        return {"openai": provider_config} if provider_config else {}
    if provider == "minimax":
        provider_config = {}
        api_key = get_env_value("MINIMAX_API_KEY")
        if api_key:
            provider_config["api_key"] = api_key
        base_url = get_env_value("MINIMAX_BASE_URL", "MINIMAX_API_BASE")
        if base_url:
            provider_config["base_url"] = base_url
        return {"minimax": provider_config} if provider_config else {}
    return {}
