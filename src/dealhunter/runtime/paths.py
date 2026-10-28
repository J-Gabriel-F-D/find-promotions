"""Resolucao de caminhos multiplataforma.

Windows  -> %APPDATA%\\dealhunter\\...
macOS    -> ~/Library/Application Support/dealhunter/...
Linux    -> $XDG_CONFIG_HOME/dealhunter|~/.config/dealhunter

A variavel ``DEALHUNTER_HOME`` sobrepoe tudo (util para testes e para rodar
com um "perfil" isolado, ex.: ``DEALHUNTER_HOME=./.dev``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_cache_path, user_config_path, user_data_path, user_log_path

APP_NAME = "dealhunter"
ENV_HOME = "DEALHUNTER_HOME"


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Diretorios e arquivos usados pela aplicacao."""

    config_dir: Path
    data_dir: Path
    cache_dir: Path
    log_dir: Path

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.toml"

    @property
    def database_file(self) -> Path:
        return self.data_dir / "dealhunter.db"

    @property
    def log_file(self) -> Path:
        return self.log_dir / "dealhunter.log"

    @property
    def lock_file(self) -> Path:
        return self.data_dir / "monitor.lock"

    def ensure_directories(self) -> None:
        for directory in (self.config_dir, self.data_dir, self.cache_dir, self.log_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def as_dict(self) -> dict[str, str]:
        return {
            "config_dir": str(self.config_dir),
            "config_file": str(self.config_file),
            "data_dir": str(self.data_dir),
            "database": str(self.database_file),
            "cache_dir": str(self.cache_dir),
            "log_file": str(self.log_file),
        }


def resolve_paths(env: dict[str, str] | None = None) -> AppPaths:
    """Calcula os caminhos do aplicativo respeitando o sistema operacional."""
    environ = os.environ if env is None else env
    override = environ.get(ENV_HOME, "").strip()

    if override:
        home = Path(override).expanduser().resolve()
        return AppPaths(
            config_dir=home / "config",
            data_dir=home / "data",
            cache_dir=home / "cache",
            log_dir=home / "logs",
        )

    return AppPaths(
        config_dir=user_config_path(APP_NAME, appauthor=False, roaming=True),
        data_dir=user_data_path(APP_NAME, appauthor=False, roaming=True),
        cache_dir=user_cache_path(APP_NAME, appauthor=False),
        log_dir=user_log_path(APP_NAME, appauthor=False),
    )
