"""Renderizacao: saida humana (Rich), JSON para automacao e modo silencioso."""

from __future__ import annotations

import json
import sys
from typing import Any

from dealhunter.cli.exit_codes import ExitCode

SCHEMA_VERSION = "1.0"


def emit_json(payload: dict[str, Any], *, stream: Any = None) -> None:
    """Escreve JSON no stdout sem interferencia do Rich (nunca quebra pipes)."""
    target = stream or sys.stdout
    target.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    target.write("\n")
    target.flush()


def envelope(command: str, *, generated_at: str, **payload: Any) -> dict[str, Any]:
    """Envelope padrao de toda saida ``--json``."""
    return {
        "schema_version": SCHEMA_VERSION,
        "command": command,
        "generated_at": generated_at,
        **payload,
    }


__all__ = ["ExitCode", "SCHEMA_VERSION", "emit_json", "envelope"]
