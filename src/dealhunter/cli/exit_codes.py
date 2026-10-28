"""Codigos de saida estaveis (contrato para scripts/automacao)."""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    OK = 0
    ERROR = 1
    USAGE = 2
    NO_RESULTS = 3
    PARTIAL_FAILURE = 4
    ALL_SOURCES_FAILED = 5
    CONFIG_ERROR = 6
    INTERRUPTED = 130
