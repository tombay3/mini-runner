from __future__ import annotations

import logging
import logging.config
import os
from typing import Any

from flask.logging import default_handler


APP_LOGGER_NAME = "loderunner.agent"
_CONFIGURED = False


def debug_log_enabled() -> bool:
    return os.environ.get("AGENT_DEBUG_LOG", "").strip().lower() in {"1", "true", "yes", "on"}


def effective_app_log_level_name() -> str:
    if debug_log_enabled():
        return "DEBUG"
    return os.environ.get("APP_LOG_LEVEL", "INFO").upper()


def configure_logging() -> logging.Logger:
    global _CONFIGURED
    if _CONFIGURED:
        return logging.getLogger(APP_LOGGER_NAME)

    app_level_name = effective_app_log_level_name()
    app_level = getattr(logging, app_level_name, logging.INFO)
    log_format = os.environ.get("APP_LOG_FORMAT", "plain").lower()
    format_string = (
        "%(asctime)s level=%(levelname)s logger=%(name)s %(message)s"
        if log_format == "plain"
        else "%(asctime)s level=%(levelname)s logger=%(name)s %(message)s"
    )

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "plain": {
                    "format": format_string,
                    "datefmt": "%Y-%m-%dT%H:%M:%S",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "plain",
                    "level": app_level_name,
                }
            },
            "root": {
                "level": "WARNING",
                "handlers": ["console"],
            },
            "loggers": {
                APP_LOGGER_NAME: {
                    "handlers": ["console"],
                    "level": app_level_name,
                    "propagate": False,
                },
                "werkzeug": {
                    "handlers": ["console"],
                    "level": "WARNING",
                    "propagate": False,
                },
            },
        }
    )

    _CONFIGURED = True
    logger = logging.getLogger(APP_LOGGER_NAME)
    logger.setLevel(app_level)
    return logger


def refresh_app_log_level() -> None:
    app_level_name = effective_app_log_level_name()
    app_level = getattr(logging, app_level_name, logging.INFO)
    logger = logging.getLogger(APP_LOGGER_NAME)
    logger.setLevel(app_level)
    for handler in logger.handlers:
        handler.setLevel(app_level)


def normalize_flask_logger(app) -> None:
    base_logger = configure_logging()
    refresh_app_log_level()
    app_logger = app.logger

    if default_handler in app_logger.handlers:
        app_logger.removeHandler(default_handler)
    app_logger.handlers[:] = list(base_logger.handlers)
    app_logger.setLevel(base_logger.level)
    app_logger.propagate = False

    werkzeug_logger = logging.getLogger("werkzeug")
    werkzeug_logger.setLevel(logging.WARNING)
    werkzeug_logger.propagate = False


def get_logger(name: str | None = None) -> logging.Logger:
    base = APP_LOGGER_NAME if not name else f"{APP_LOGGER_NAME}.{name}"
    return logging.getLogger(base)


def log_event(logger: logging.Logger, severity: int, event: str, **fields: Any) -> None:
    parts = [f"event={event}"]
    for key, value in fields.items():
        if value is None or value == "":
            continue
        normalized = str(value).replace("\n", "\\n")
        parts.append(f"{key}={normalized}")
    logger.log(severity, " ".join(parts))
