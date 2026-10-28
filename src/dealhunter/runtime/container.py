"""Composition root: monta configuracao, logging, console e persistencia.

Nenhuma regra de negocio mora aqui. O container apenas liga as pecas e expoe
um ``RuntimeContext`` imutavel para os comandos da CLI.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from rich.console import Console

from dealhunter import __version__
from dealhunter.adapters.storage.database import Database
from dealhunter.domain.ports.clock import Clock, SystemClock
from dealhunter.runtime.config import AppConfig, ConfigLoadResult, load_config
from dealhunter.runtime.logging import configure_logging
from dealhunter.runtime.paths import AppPaths, resolve_paths


@dataclass(frozen=True, slots=True)
class RuntimeFlags:
    json_output: bool = False
    quiet: bool = False
    debug: bool = False
    no_color: bool = False
    no_unicode: bool = False
    ai_disabled: bool = False


@dataclass(frozen=True, slots=True)
class RuntimeContext:
    config: AppConfig
    config_load: ConfigLoadResult
    paths: AppPaths
    flags: RuntimeFlags
    clock: Clock
    logger: Any
    console: Console
    error_console: Console
    database: Database

    @property
    def json_output(self) -> bool:
        return self.flags.json_output

    @property
    def quiet(self) -> bool:
        return self.flags.quiet

    @property
    def ai_enabled(self) -> bool:
        return self.config.ai.enabled and not self.flags.ai_disabled


def _make_console(*, stderr: bool, no_color: bool, json_output: bool, unicode: bool) -> Console:
    color_enabled = not no_color and not json_output
    target = sys.stderr if stderr else sys.stdout
    # Redirecionado para arquivo/pipe o Rich assume 80 colunas e quebra caminhos;
    # 110 mantem a tabela legivel sem inventar largura de terminal.
    width = None if target.isatty() else 110
    return Console(
        stderr=stderr,
        force_terminal=None if color_enabled else False,
        no_color=not color_enabled,
        highlight=False,
        soft_wrap=False,
        emoji=unicode,
        legacy_windows=False,
        width=width,
    )


def build_runtime(
    *,
    config_path: Path | None = None,
    project_dir: Path | None = None,
    flags: RuntimeFlags | None = None,
    clock: Clock | None = None,
    environ: dict[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> RuntimeContext:
    """Monta o contexto de execucao usado por todos os comandos."""
    flags = flags or RuntimeFlags()
    paths = resolve_paths(environ)
    config_load = load_config(
        paths, explicit_path=config_path, project_dir=project_dir, environ=environ
    )
    config = config_load.config

    if flags.ai_disabled:
        config = config.model_copy(update={"ai": config.ai.model_copy(update={"enabled": False})})

    log_level = "debug" if flags.debug else config.general.log_level
    logger = configure_logging(
        level=log_level,
        json_console=flags.json_output,
        log_file=None if flags.quiet else paths.log_file,
        stream=stderr or sys.stderr,
    )

    console = _make_console(
        stderr=False,
        no_color=flags.no_color,
        json_output=flags.json_output,
        unicode=config.general.unicode and not flags.no_unicode,
    )
    error_console = _make_console(
        stderr=True,
        no_color=flags.no_color,
        json_output=flags.quiet,
        unicode=config.general.unicode and not flags.no_unicode,
    )
    if stdout is not None:
        console = Console(file=stdout, no_color=True, highlight=False, width=200)

    return RuntimeContext(
        config=config,
        config_load=config_load,
        paths=paths,
        flags=flags,
        clock=clock or SystemClock(),
        logger=logger,
        console=console,
        error_console=error_console,
        database=Database(paths.database_file),
    )


def version_info() -> dict[str, str]:
    """Metadados de versao exibidos em ``--version`` e ``status --json``."""
    import platform

    return {
        "name": "dealhunter",
        "version": __version__,
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
    }
