"""structlog: человекочитаемо в терминале, JSON по флагу. Секреты в лог не пишем."""

from __future__ import annotations

import logging
import re
import sys

import structlog

_SECRET_KEYS = re.compile(r"(token|secret|password|api_key|apikey|authorization)", re.I)


def _redact(_logger, _name, event_dict):
    for key in list(event_dict):
        if _SECRET_KEYS.search(key):
            event_dict[key] = "***"
    return event_dict


class _Stderr:
    """Ленивая ссылка на sys.stderr (CliRunner и pytest подменяют поток)."""

    def write(self, s: str) -> int:
        return sys.stderr.write(s)

    def flush(self) -> None:
        sys.stderr.flush()


def configure(json: bool = False, verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _redact,
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer(),
    ]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=_Stderr()),
        cache_logger_on_first_use=False,
    )


structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.INFO))


def get(name: str = "techstudio"):
    return structlog.get_logger(name)
