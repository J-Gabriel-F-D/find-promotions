"""Privacidade: exportação, esquecimento, retenção e minimização."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from typer.testing import CliRunner

from dealhunter.cli.app import app
from dealhunter.runtime.paths import resolve_paths

runner = CliRunner()


def _home(tmp_path: Path) -> Path:
    return tmp_path / "home"


def _invoke(home: Path, args: list[str]):
    return runner.invoke(app, args, env={"DEALHUNTER_HOME": str(home)})


def _write_config(home: Path, body: str) -> None:
    config_file = home / "config" / "config.toml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(body, encoding="utf-8")


def _db_path(home: Path) -> Path:
    return resolve_paths({"DEALHUNTER_HOME": str(home)}).database_file


def _create_and_check(home: Path, *, count: int = 1) -> list[int]:
    ids: list[int] = []
    for index in range(count):
        created = _invoke(
            home,
            [
                "--json",
                "alerts",
                "create",
                "redmi",
                "--max-price",
                "1700",
                "--label",
                f"alerta {index}",
            ],
        )
        assert created.exit_code == 0, created.output
        ids.append(json.loads(created.output)["alert_id"])
    checked = _invoke(home, ["--json", "alerts", "check", "--source", "fixture"])
    assert checked.exit_code == 0, checked.output
    return ids


class TestPrivacyExport:
    def test_exporta_alertas_e_mascara_contato(self, tmp_path: Path) -> None:
        home = _home(tmp_path)
        _write_config(
            home,
            "\n".join(
                [
                    "[notifications]",
                    'email_to = "joao.silva@example.com"',
                    "",
                ]
            ),
        )
        _create_and_check(home)

        result = _invoke(home, ["--json", "privacy", "export"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["command"] == "privacy.export"
        assert payload["counts"] == {
            "alerts": 1,
            "events": 1,
            "notifications": 1,
        }
        assert payload["alerts"][0]["label"] == "alerta 0"
        assert payload["alerts"][0]["query"] == "redmi"
        assert payload["alerts"][0]["channels"] == ["console"]
        assert payload["profile"]["notifications"]["email_to"] == "j***@example.com"
        assert "joao.silva@example.com" not in result.output
        assert "destination" not in json.dumps(payload)

    def test_export_com_contatos_reais_sob_opt_in(self, tmp_path: Path) -> None:
        home = _home(tmp_path)
        _write_config(
            home,
            "\n".join(
                [
                    "[notifications]",
                    'email_to = "joao.silva@example.com"',
                    "",
                ]
            ),
        )

        result = _invoke(home, ["--json", "privacy", "export", "--include-contacts"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["profile"]["notifications"]["email_to"] == (
            "joao.silva@example.com"
        )

    def test_export_sem_dados(self, tmp_path: Path) -> None:
        result = _invoke(_home(tmp_path), ["--json", "privacy", "export"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["counts"] == {"alerts": 0, "events": 0, "notifications": 0}
        assert payload["alerts"] == []

    def test_export_recusa_sobrescrever_sem_force(self, tmp_path: Path) -> None:
        home = _home(tmp_path)
        output = tmp_path / "export.json"
        output.write_text("existente", encoding="utf-8")

        result = _invoke(home, ["--json", "privacy", "export", "--output", str(output)])
        assert result.exit_code == 1
        assert output.read_text(encoding="utf-8") == "existente"

    def test_export_grava_arquivo_e_resume_em_json(self, tmp_path: Path) -> None:
        home = _home(tmp_path)
        _create_and_check(home)
        output = tmp_path / "export.json"

        result = _invoke(home, ["--json", "privacy", "export", "--output", str(output)])
        assert result.exit_code == 0, result.output
        summary = json.loads(result.output)
        assert summary["output"] == str(output)
        assert summary["counts"]["alerts"] == 1

        exported = json.loads(output.read_text(encoding="utf-8"))
        assert exported["command"] == "privacy.export"
        assert exported["alerts"][0]["label"] == "alerta 0"


class TestPrivacyForget:
    def test_forget_exige_confirmacao(self, tmp_path: Path) -> None:
        home = _home(tmp_path)
        _create_and_check(home)

        result = _invoke(home, ["--json", "privacy", "forget"])
        assert result.exit_code == 2
        assert (
            json.loads(_invoke(home, ["--json", "privacy", "export"]).output)["counts"]["alerts"]
            == 1
        )

    def test_forget_remove_alertas_eventos_e_notificacoes(self, tmp_path: Path) -> None:
        home = _home(tmp_path)
        _create_and_check(home)

        result = _invoke(home, ["--json", "privacy", "forget", "--yes"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["deleted"] == {
            "alert": 1,
            "alert_event": 1,
            "notification": 1,
            "alert_dedupe": 1,
        }

        with closing(sqlite3.connect(_db_path(home))) as connection:
            for table in ("alert", "alert_event", "notification", "alert_dedupe"):
                assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0

        listed = _invoke(home, ["--json", "alerts", "list"])
        assert json.loads(listed.output)["alerts"] == []


class TestPrivacyRetention:
    def test_retencao_simula_antes_de_apagar(self, tmp_path: Path) -> None:
        home = _home(tmp_path)
        _create_and_check(home)
        with closing(sqlite3.connect(_db_path(home))) as connection:
            connection.execute("UPDATE alert_event SET created_at = '2020-01-01T00:00:00+00:00'")
            connection.execute("UPDATE notification SET created_at = '2020-01-01T00:00:00+00:00'")
            connection.commit()

        simulated = _invoke(home, ["--json", "privacy", "retention", "--days", "30"])
        assert simulated.exit_code == 0, simulated.output
        payload = json.loads(simulated.output)
        assert payload["applied"] is False
        assert payload["counts"] == {"events": 1, "notifications": 1}

        with closing(sqlite3.connect(_db_path(home))) as connection:
            assert connection.execute("SELECT COUNT(*) FROM alert_event").fetchone()[0] == 1

    def test_retencao_preserva_registros_recentes(self, tmp_path: Path) -> None:
        home = _home(tmp_path)
        ids = _create_and_check(home, count=2)
        with closing(sqlite3.connect(_db_path(home))) as connection:
            connection.execute(
                "UPDATE alert_event SET created_at = '2020-01-01T00:00:00+00:00' "
                "WHERE alert_id = ?",
                (ids[0],),
            )
            connection.execute(
                "UPDATE notification SET created_at = '2020-01-01T00:00:00+00:00' "
                "WHERE event_id IN (SELECT id FROM alert_event WHERE alert_id = ?)",
                (ids[0],),
            )
            connection.commit()

        applied = _invoke(home, ["--json", "privacy", "retention", "--days", "30", "--apply"])
        assert applied.exit_code == 0, applied.output
        assert json.loads(applied.output)["counts"] == {
            "events": 1,
            "notifications": 1,
        }

        with closing(sqlite3.connect(_db_path(home))) as connection:
            assert connection.execute("SELECT COUNT(*) FROM alert_event").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM notification").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM alert").fetchone()[0] == 2
            assert connection.execute("SELECT COUNT(*) FROM alert_dedupe").fetchone()[0] == 2

        # A retenção não pode reabrir notificações já enviadas para a mesma
        # oferta/faixa de preço: a chave de dedupe sobrevive ao evento detalhado.
        rechecked = _invoke(home, ["--json", "alerts", "check", "--source", "fixture"])
        assert rechecked.exit_code == 0, rechecked.output
        with closing(sqlite3.connect(_db_path(home))) as connection:
            assert connection.execute("SELECT COUNT(*) FROM alert_event").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM notification").fetchone()[0] == 1
