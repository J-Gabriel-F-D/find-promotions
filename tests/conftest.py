"""Fixtures compartilhadas."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from dealhunter.runtime.paths import AppPaths, resolve_paths


@pytest.fixture()
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[AppPaths]:
    """Isola config/dados/logs em um diretorio temporario."""
    home = tmp_path / "home"
    monkeypatch.setenv("DEALHUNTER_HOME", str(home))
    paths = resolve_paths()
    paths.ensure_directories()
    yield paths
