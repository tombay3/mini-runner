from __future__ import annotations


class AgentError(Exception):
    """Base exception for backend agent failures."""


class AgentRequestError(AgentError, ValueError):
    """Raised when a client request is invalid."""


class AgentConfigError(AgentError, RuntimeError):
    """Raised when the backend agent is not configured correctly."""


class AgentExecutionError(AgentError, RuntimeError):
    """Raised when the backend agent cannot produce a valid action."""
