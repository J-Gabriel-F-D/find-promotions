"""Contrato do comando ``dealhunter ui`` sem abrir janela nem importar Tkinter."""

from __future__ import annotations

import re
import sys
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dealhunter.cli.app import app
from dealhunter.gui.errors import GuiUnavailable

runner = CliRunner()
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _invoke(tmp_path: Path, args: list[str]):
    return runner.invoke(app, args, env={"DEALHUNTER_HOME": str(tmp_path / "home")})


def _flat(text: str) -> str:
    return "".join(_ANSI_RE.sub("", text).split()).lower()


def test_ui_help_does_not_require_tkinter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Se o comando importar Tkinter para montar a ajuda, este teste falha.
    monkeypatch.setitem(sys.modules, "tkinter", None)
    monkeypatch.delitem(sys.modules, "dealhunter.gui.app", raising=False)

    result = _invoke(tmp_path, ["ui", "--help"])

    assert result.exit_code == 0
    assert "interfacegráfica" in _flat(result.output) or "interfacegrafica" in _flat(result.output)
    assert "dealhunter.gui.app" not in sys.modules


def test_ui_missing_tkinter_exit_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "dealhunter.gui.app", None)

    result = _invoke(tmp_path, ["ui"])

    assert result.exit_code == 1
    assert "tkinter" in _flat(result.output)


def test_ui_without_display_exit_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_app = types.ModuleType("dealhunter.gui.app")

    def launch(_rt: object) -> None:
        raise GuiUnavailable("ambiente sem display")

    fake_app.launch = launch  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "dealhunter.gui.app", fake_app)

    result = _invoke(tmp_path, ["ui"])

    assert result.exit_code == 1
    assert "semdisplay" in _flat(result.output)


def test_ui_rejects_json_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[bool] = []
    fake_app = types.ModuleType("dealhunter.gui.app")
    fake_app.launch = lambda _rt: called.append(True)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "dealhunter.gui.app", fake_app)

    result = _invoke(tmp_path, ["--json", "ui"])

    assert result.exit_code == 2
    assert called == []
    assert "json" in _flat(result.output)
