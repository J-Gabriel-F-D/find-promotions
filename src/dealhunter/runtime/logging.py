"""Logging estruturado com redacao de segredos.

Regras
------
* stdout e **exclusivo** para dados (resultados, JSON). Logs vao para stderr e,
  opcionalmente, para arquivo em JSON.
* Qualquer chave que pareca segredo e mascarada antes de sair do processo.
* Emails são parcialmente mascarados para reduzir PII em log (LGPD).
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any, TextIO, cast

import structlog
from structlog.types import Processor

_SECRET_KEY = re.compile(
    r"(pass(word)?|token|secret|api[_-]?key|authorization|cookie|session|credential)",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"([A-Za-z0-9._%+-])([A-Za-z0-9._%+-]*)(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_MASK = "***"


def _mask_email(match: re.Match[str]) -> str:
    return f"{match.group(1)}{_MASK}{match.group(3)}"


def _scrub(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return _MASK
    if isinstance(value, str):
        return _EMAIL.sub(_mask_email, value)
    if isinstance(value, dict):
        return {
            key: (_MASK if _SECRET_KEY.search(str(key)) else _scrub(item, depth + 1))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return type(value)(_scrub(item, depth + 1) for item in value)
    return value


def redact_secrets(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Processor do structlog que remove segredos/PII dos eventos."""
    return cast(MutableMapping[str, Any], _scrub(dict(event_dict)))


def _console_renderer(json_console: bool) -> Processor:
    if json_console:
        return structlog.processors.JSONRenderer(ensure_ascii=False)
    return structlog.dev.ConsoleRenderer(
        colors=sys.stderr.isatty(),
        exception_formatter=structlog.dev.plain_traceback,
    )


def configure_logging(
    *,
    level: str = "info",
    json_console: bool = False,
    log_file: Path | None = None,
    stream: TextIO | None = None,
) -> structlog.stdlib.BoundLogger:
    """Configura structlog + logging padrão e devolve o logger raiz da app."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_secrets,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(numeric_level)

    console_handler = logging.StreamHandler(stream or sys.stderr)
    console_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                _console_renderer(json_console),
            ],
        )
    )
    root.addHandler(console_handler)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                foreign_pre_chain=shared,
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.processors.JSONRenderer(ensure_ascii=False),
                ],
            )
        )
        root.addHandler(file_handler)

    # Bibliotecas de terceiros passam pelo mesmo pipeline (sem poluir o stdout).
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(max(numeric_level, logging.WARNING))

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger("dealhunter"))
