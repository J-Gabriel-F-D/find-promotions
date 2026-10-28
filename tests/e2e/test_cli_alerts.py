"""Testes ponta a ponta dos alertas e notificacoes."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from dealhunter.cli.app import app

runner = CliRunner()


def _invoke(tmp_path: Path, args: list[str]):
    return runner.invoke(app, args, env={"DEALHUNTER_HOME": str(tmp_path / "home")})


class TestAlerts:
    def test_ciclo_completo_de_alerta(self, tmp_path: Path) -> None:
        created = _invoke(
            tmp_path,
            ["--json", "alerts", "create", "Redmi Note 14 256GB", "--max-price", "1700"],
        )
        assert created.exit_code == 0, created.output
        alert_id = json.loads(created.output)["alert_id"]

        listed = _invoke(tmp_path, ["--json", "alerts", "list"])
        alerts = json.loads(listed.output)["alerts"]
        assert [alert["id"] for alert in alerts] == [alert_id]
        assert alerts[0]["rule"] == "<= R$ 1.700,00"

        checked = _invoke(
            tmp_path, ["--json", "alerts", "check", str(alert_id), "--source", "fixture"]
        )
        assert checked.exit_code == 0, checked.output

        outcome = json.loads(checked.output)["outcomes"][0]
        assert outcome["matched"] is True
        assert outcome["price_cents"] <= 170_000
        assert outcome["channels"][0]["channel"] == "console"
        assert outcome["channels"][0]["ok"] is True

    def test_nao_notifica_duas_vezes_a_mesma_faixa(self, tmp_path: Path) -> None:
        _invoke(
            tmp_path,
            ["alerts", "create", "Redmi Note 14 256GB", "--max-price", "1700"],
        )
        _invoke(tmp_path, ["alerts", "check", "--source", "fixture"])

        second = _invoke(tmp_path, ["--json", "alerts", "check", "--source", "fixture"])
        outcome = json.loads(second.output)["outcomes"][0]
        assert outcome["matched"] is True
        assert "já notificado" in outcome["note"]
        assert outcome["channels"] == []

    def test_alerta_exige_uma_regra(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["alerts", "create", "redmi"])
        assert result.exit_code != 0
        assert "max-price" in result.output or "discount" in result.output

    def test_pausar_impede_checagem(self, tmp_path: Path) -> None:
        created = _invoke(
            tmp_path, ["--json", "alerts", "create", "redmi", "--max-price", "999999"]
        )
        alert_id = json.loads(created.output)["alert_id"]

        paused = _invoke(tmp_path, ["--json", "alerts", "pause", str(alert_id)])
        assert paused.exit_code == 0, paused.output

        checked = _invoke(tmp_path, ["--json", "alerts", "check", "--source", "fixture"])
        assert json.loads(checked.output)["outcomes"] == []

        resumed = _invoke(tmp_path, ["--json", "alerts", "resume", str(alert_id)])
        assert resumed.exit_code == 0, resumed.output

    def test_remover_alerta(self, tmp_path: Path) -> None:
        created = _invoke(
            tmp_path, ["--json", "alerts", "create", "redmi", "--max-price", "999999"]
        )
        alert_id = json.loads(created.output)["alert_id"]

        deleted = _invoke(tmp_path, ["--json", "alerts", "delete", str(alert_id)])
        assert deleted.exit_code == 0, deleted.output
        assert json.loads(deleted.output)["deleted"] is True

        listed = _invoke(tmp_path, ["--json", "alerts", "list"])
        assert json.loads(listed.output)["alerts"] == []


class TestNotify:
    def test_status_lista_canal_console(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["--json", "notify", "status"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert "console" in payload["available"]
        # Sem SMTP configurado, o canal de e-mail nao e anunciado como pronto.
        assert "email" not in payload["available"]

    def test_envio_de_teste_pelo_console(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["--json", "notify", "test", "--channel", "console"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["results"] == [{"channel": "console", "ok": True, "error": None}]

    def test_canal_inexistente_falha_sem_quebrar(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["--json", "notify", "test", "--channel", "telegram"])
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["results"][0]["ok"] is False
