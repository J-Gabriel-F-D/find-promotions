"""Testes de ponta a ponta da CLI (renderizacao e contrato JSON)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from dealhunter import __version__
from dealhunter.cli.app import app

runner = CliRunner()


def _invoke(tmp_path: Path, args: list[str]):
    return runner.invoke(app, args, env={"DEALHUNTER_HOME": str(tmp_path / "home")})


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_help_lista_comandos(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["--help"])
    assert result.exit_code == 0
    for command in ("status", "config", "db"):
        assert command in result.output


def test_status_json_tem_envelope_estavel(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["--json", "status"])
    assert result.exit_code == 0, result.output

    payload = json.loads(result.output)
    assert payload["schema_version"] == "1.1"
    assert payload["command"] == "status"
    assert payload["version"] == __version__
    assert payload["database"]["initialized"] is False
    assert payload["ai"]["enabled"] is False
    assert "generated_at" in payload


def test_db_migrate_e_status(tmp_path: Path) -> None:
    migrated = _invoke(tmp_path, ["--json", "db", "migrate"])
    assert migrated.exit_code == 0, migrated.output
    assert json.loads(migrated.output)["schema_version"] == "0004_privacidade"

    status = _invoke(tmp_path, ["--json", "status"])
    payload = json.loads(status.output)
    assert payload["database"]["initialized"] is True
    assert payload["database"]["schema_version"] == "0004_privacidade"
    assert payload["database"]["integrity_ok"] is True


def test_config_path_json(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["--json", "config", "path"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["paths"]["database"].endswith("dealhunter.db")


def test_quiet_reduz_saida(tmp_path: Path) -> None:
    result = _invoke(tmp_path, ["--quiet", "status"])
    assert result.exit_code == 0
    assert len(result.output.strip().splitlines()) == 1


def test_config_invalida_retorna_codigo_proprio(tmp_path: Path) -> None:
    home = tmp_path / "home"
    config_dir = home / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text("[general]\nresults_limit = 0\n", encoding="utf-8")

    result = runner.invoke(app, ["status"], env={"DEALHUNTER_HOME": str(home)})
    assert result.exit_code == 6
    assert "configuração inválida" in result.output.lower()
