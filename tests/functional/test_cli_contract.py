"""Contrato funcional da CLI: argumentos, saída, códigos de erro e flags globais."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dealhunter.cli.app import app

runner = CliRunner()


def _invoke(tmp_path: Path, args: list[str], *, env: dict[str, str] | None = None):
    full_env = {"DEALHUNTER_HOME": str(tmp_path / "home")}
    full_env.update(env or {})
    return runner.invoke(app, args, env=full_env)


class TestGlobalContract:
    def test_version(self) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "dealhunter" in result.output

    def test_ajuda_sem_argumentos(self) -> None:
        result = runner.invoke(app, [])
        assert result.exit_code == 2
        assert "search" in result.output
        assert "alerts" in result.output

    def test_comando_desconhecido(self) -> None:
        result = runner.invoke(app, ["nao-existe"])
        assert result.exit_code == 2

    def test_opcao_desconhecida(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["status", "--nao-existe"])
        assert result.exit_code == 2

    def test_config_explicito(self, tmp_path: Path) -> None:
        config = tmp_path / "custom.toml"
        config.write_text('[general]\nlanguage = "pt-BR"\ntimezone = "UTC"\n', encoding="utf-8")
        result = _invoke(tmp_path, ["--config", str(config), "--json", "status"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["config"]["timezone"] == "UTC"

    def test_config_inexistente_exit_6(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["--config", str(tmp_path / "nada.toml"), "status"])
        assert result.exit_code == 6


class TestSearchArguments:
    def test_busca_sem_termo_e_uso_invalido(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["search"])
        assert result.exit_code == 2
        assert "informe" in result.output

    @pytest.mark.parametrize(
        ("args", "fragment"),
        [
            (["--limit", "0"], "limit"),
            (["--max-price", "abc"], "max-price"),
            (["--max-price", "-1"], "greater"),
            (["--condition", "quebrado"], "condition"),
            (["--sort", "quebrado"], "sort"),
        ],
    )
    def test_argumentos_invalidos(self, tmp_path: Path, args: list[str], fragment: str) -> None:
        result = _invoke(tmp_path, ["search", "redmi", "--source", "fixture", *args])
        assert result.exit_code == 2
        assert fragment.lower() in result.output.lower()

    def test_sem_resultados_exit_3(self, tmp_path: Path) -> None:
        result = _invoke(
            tmp_path,
            ["--json", "search", "produto-que-nao-existe-xyz", "--source", "fixture"],
        )
        assert result.exit_code == 3
        assert json.loads(result.output)["results"] == []

    def test_json_tem_schema_e_stdout_valido(self, tmp_path: Path) -> None:
        result = _invoke(
            tmp_path, ["--json", "search", "Redmi Note 14 256GB", "--source", "fixture"]
        )
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["schema_version"] == "1.1"
        assert payload["command"] == "search"

    def test_quiet_imprime_uma_linha(self, tmp_path: Path) -> None:
        result = _invoke(
            tmp_path, ["--quiet", "search", "Redmi Note 14 256GB", "--source", "fixture"]
        )
        assert result.exit_code == 0
        lines = [line for line in result.output.splitlines() if line.strip()]
        assert len(lines) == 1
        assert "|" in lines[0]

    def test_no_unicode_usa_ascii(self, tmp_path: Path) -> None:
        result = _invoke(
            tmp_path,
            ["--no-unicode", "search", "Redmi Note 14 256GB", "--source", "fixture"],
        )
        assert result.exit_code == 0
        forbidden = set("─│┌┐└┘├┤┬┴┼█·★⚠→")
        assert not (set(result.output) & forbidden)

    def test_no_color_nao_emite_ansi(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["--no-color", "search", "redmi", "--source", "fixture"])
        assert result.exit_code == 0
        assert "\x1b[" not in result.output

    def test_no_ai_e_aceito(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["--no-ai", "--json", "status"])
        assert result.exit_code == 0
        assert json.loads(result.output)["ai"]["enabled"] is False

    def test_debug_nao_vaza_traceback(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["--debug", "--json", "status"])
        assert result.exit_code == 0
        assert "Traceback" not in result.output


class TestCommandsAfterSearch:
    @pytest.fixture()
    def populated(self, tmp_path: Path) -> Path:
        result = _invoke(tmp_path, ["search", "Redmi Note 14 256GB", "--source", "fixture"])
        assert result.exit_code == 0, result.output
        return tmp_path

    def test_history(self, populated: Path) -> None:
        result = _invoke(populated, ["--json", "history", "Redmi Note 14 256GB"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["command"] == "history"
        assert payload["points"]

    def test_coupons(self, populated: Path) -> None:
        result = _invoke(populated, ["--json", "coupons", "list"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["command"] == "coupons.list"

    def test_promotions(self, populated: Path) -> None:
        result = _invoke(populated, ["--json", "promotions", "--source", "fixture"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["command"] == "promotions"

    def test_reviews(self, populated: Path) -> None:
        result = _invoke(populated, ["--json", "reviews", "Redmi Note 14 256GB"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["sources"]

    def test_db_info(self, populated: Path) -> None:
        result = _invoke(populated, ["--json", "db", "info"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["integrity_ok"] is True

    def test_notify_status(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["--json", "notify", "status"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["command"] == "notify.status"
        assert "console" in payload["available"]

    def test_notify_test_console(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["notify", "test", "--channel", "console"])
        assert result.exit_code == 0, result.output
        assert "console" in result.output.lower()

    def test_alerta_inexistente_delete_exit_3(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["alerts", "delete", "9999"])
        assert result.exit_code == 3

    def test_alerta_inexistente_delete_json_exit_3(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["--json", "alerts", "delete", "9999"])
        assert result.exit_code == 3
        assert json.loads(result.output)["deleted"] is False


class TestErrorHandling:
    def test_comando_sem_banco_cria_quando_necessario(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["--json", "alerts", "list"])
        assert result.exit_code == 0
        assert json.loads(result.output)["alerts"] == []

    def test_json_de_erro_de_uso_nao_polui_stdout(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["--json", "search"])
        assert result.exit_code == 2
        assert not re.search(r"^\s*\{", result.output or "")
