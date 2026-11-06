"""Edição das regras inteligentes de alertas existentes."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from dealhunter.cli.app import app

runner = CliRunner()


def _invoke(tmp_path: Path, args: list[str]):
    return runner.invoke(app, args, env={"DEALHUNTER_HOME": str(tmp_path / "home")})


def _create(tmp_path: Path, *extra: str) -> int:
    result = _invoke(
        tmp_path,
        ["--json", "alerts", "create", "redmi", "--max-price", "2000", *extra],
    )
    assert result.exit_code == 0, result.output
    return int(json.loads(result.output)["alert_id"])


class TestRuleShow:
    def test_mostra_regra_criada(self, tmp_path: Path) -> None:
        alert_id = _create(
            tmp_path,
            "--min-trust",
            "60",
            "--max-risk",
            "moderate",
            "--min-analysis-confidence",
            "0.3",
        )

        result = _invoke(tmp_path, ["--json", "alerts", "rule", "show", str(alert_id)])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["found"] is True
        rule = payload["rule"]
        assert rule["min_trust"] == 60.0
        assert rule["max_risk"] == "moderate"
        assert rule["min_analysis_confidence"] == 0.3
        assert rule["require_real_discount"] is False
        assert rule["description"]

    def test_alerta_sem_filtros_mostra_vazio(self, tmp_path: Path) -> None:
        alert_id = _create(tmp_path)

        result = _invoke(tmp_path, ["--json", "alerts", "rule", "show", str(alert_id)])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["found"] is True
        assert payload["rule"]["description"] == []
        assert payload["rule"]["min_trust"] is None

    def test_alerta_sem_filtros_saida_humana(self, tmp_path: Path) -> None:
        alert_id = _create(tmp_path)

        result = _invoke(tmp_path, ["alerts", "rule", "show", str(alert_id)])

        assert result.exit_code == 0, result.output
        assert "sem filtros inteligentes" in result.output

    def test_alerta_inexistente_devolve_no_results(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["--json", "alerts", "rule", "show", "999"])

        assert result.exit_code == 3
        payload = json.loads(result.output)
        assert payload["found"] is False


class TestRuleSet:
    def test_substitui_filtros_anteriores(self, tmp_path: Path) -> None:
        alert_id = _create(tmp_path, "--min-trust", "50")

        changed = _invoke(
            tmp_path,
            [
                "--json",
                "alerts",
                "rule",
                "set",
                str(alert_id),
                "--max-risk",
                "low",
                "--require-real-discount",
            ],
        )
        assert changed.exit_code == 0, changed.output
        assert json.loads(changed.output)["changed"] is True

        shown = _invoke(tmp_path, ["--json", "alerts", "rule", "show", str(alert_id)])
        rule = json.loads(shown.output)["rule"]
        assert rule["min_trust"] is None
        assert rule["max_risk"] == "low"
        assert rule["require_real_discount"] is True

        listed = _invoke(tmp_path, ["--json", "alerts", "list"])
        alert = json.loads(listed.output)["alerts"][0]
        assert "confiança >= 50" not in alert["smart_rule"]
        assert "risco <= low" in alert["smart_rule"]

    def test_set_sem_filtros_e_erro_de_uso(self, tmp_path: Path) -> None:
        alert_id = _create(tmp_path)

        result = _invoke(tmp_path, ["--json", "alerts", "rule", "set", str(alert_id)])

        assert result.exit_code == 2
        assert "informe ao menos um filtro" in result.output

    def test_risco_invalido_e_erro_de_uso(self, tmp_path: Path) -> None:
        alert_id = _create(tmp_path)

        result = _invoke(
            tmp_path,
            ["--json", "alerts", "rule", "set", str(alert_id), "--max-risk", "alto"],
        )

        assert result.exit_code == 2
        assert "risco" in result.output.lower()

    def test_confianca_fora_da_escala_e_erro_de_uso(self, tmp_path: Path) -> None:
        alert_id = _create(tmp_path)

        result = _invoke(
            tmp_path,
            ["--json", "alerts", "rule", "set", str(alert_id), "--min-trust", "150"],
        )

        assert result.exit_code == 2

    def test_alerta_inexistente_devolve_no_results(self, tmp_path: Path) -> None:
        result = _invoke(
            tmp_path,
            ["--json", "alerts", "rule", "set", "999", "--min-trust", "50"],
        )

        assert result.exit_code == 3
        payload = json.loads(result.output)
        assert payload["changed"] is False

    def test_regra_editada_passa_a_valer_na_checagem(self, tmp_path: Path) -> None:
        alert_id = _create(tmp_path)
        first = _invoke(
            tmp_path,
            ["--json", "alerts", "check", str(alert_id), "--source", "fixture"],
        )
        assert first.exit_code == 0, first.output
        assert json.loads(first.output)["outcomes"][0]["matched"] is True

        updated = _invoke(
            tmp_path,
            ["--json", "alerts", "rule", "set", str(alert_id), "--min-trust", "100"],
        )
        assert updated.exit_code == 0, updated.output

        # A oferta fixture não alcança confiança 100; a regra editada é aplicada.
        second = _invoke(
            tmp_path,
            ["--json", "alerts", "check", str(alert_id), "--source", "fixture"],
        )
        assert second.exit_code == 0, second.output
        payload = json.loads(second.output)["outcomes"][0]
        assert payload["matched"] is False
        assert "ninguém" not in payload["note"]
        assert "nenhuma oferta" in payload["note"]


class TestRuleClear:
    def test_limpa_filtros_mantendo_preco(self, tmp_path: Path) -> None:
        alert_id = _create(tmp_path, "--min-trust", "60", "--max-risk", "moderate")

        result = _invoke(tmp_path, ["--json", "alerts", "rule", "clear", str(alert_id)])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["changed"] is True
        assert payload["rule"]["description"] == []

        shown = _invoke(tmp_path, ["--json", "alerts", "rule", "show", str(alert_id)])
        assert json.loads(shown.output)["rule"]["min_trust"] is None

        listed = _invoke(tmp_path, ["--json", "alerts", "list"])
        alert = json.loads(listed.output)["alerts"][0]
        assert alert["rule"] == "<= R$ 2.000,00"
        assert alert["smart_rule"] == []

    def test_limpar_regra_ja_vazia_e_idempotente(self, tmp_path: Path) -> None:
        alert_id = _create(tmp_path)

        result = _invoke(tmp_path, ["--json", "alerts", "rule", "clear", str(alert_id)])

        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["changed"] is True

    def test_alerta_inexistente_devolve_no_results(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["--json", "alerts", "rule", "clear", "999"])

        assert result.exit_code == 3
        assert json.loads(result.output)["changed"] is False

    def test_saida_humana(self, tmp_path: Path) -> None:
        alert_id = _create(tmp_path, "--min-trust", "60")

        result = _invoke(tmp_path, ["alerts", "rule", "clear", str(alert_id)])

        assert result.exit_code == 0, result.output
        assert "Filtros do alerta" in result.output
        assert "removidos" in result.output
