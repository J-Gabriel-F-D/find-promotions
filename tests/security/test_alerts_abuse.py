"""Limites de abuso, deduplicação, opt-out e privacidade dos alertas."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from typer.testing import CliRunner

from dealhunter.cli.app import app
from dealhunter.runtime.paths import resolve_paths

runner = CliRunner()


def _home(tmp_path: Path, name: str = "home") -> Path:
    return tmp_path / name


def _invoke(home: Path, args: list[str], *, env: dict[str, str] | None = None):
    full_env = {"DEALHUNTER_HOME": str(home)}
    full_env.update(env or {})
    return runner.invoke(app, args, env=full_env)


def _write_config(home: Path, body: str) -> None:
    config_file = home / "config" / "config.toml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(body, encoding="utf-8")


def _db_path(home: Path) -> Path:
    return resolve_paths({"DEALHUNTER_HOME": str(home)}).database_file


class TestAlertAbuseLimits:
    def test_limite_de_alertas_ativos(self, tmp_path: Path) -> None:
        home = _home(tmp_path)
        _write_config(home, "[monitor]\nmax_active_alerts = 2\n")

        for index in range(2):
            created = _invoke(
                home,
                [
                    "--json",
                    "alerts",
                    "create",
                    f"redmi {index}",
                    "--max-price",
                    "1700",
                ],
            )
            assert created.exit_code == 0, created.output

        third = _invoke(home, ["alerts", "create", "redmi terceiro", "--max-price", "1700"])
        assert third.exit_code == 2
        assert "limite de 2 alertas" in third.output

    def test_canal_desconhecido_nao_e_aceito(self, tmp_path: Path) -> None:
        home = _home(tmp_path)
        result = _invoke(
            home,
            [
                "alerts",
                "create",
                "redmi",
                "--max-price",
                "1700",
                "--channel",
                "console\nBcc: evil@example.com",
            ],
        )
        assert result.exit_code == 2
        assert "canal" in result.output.lower()

    def test_canal_com_markup_nao_e_aceito(self, tmp_path: Path) -> None:
        home = _home(tmp_path)
        result = _invoke(
            home,
            ["alerts", "create", "redmi", "--max-price", "1700", "--channel", "[red]x"],
        )
        assert result.exit_code == 2

    def test_quebra_de_linha_no_nome_do_alerta_e_recusada(self, tmp_path: Path) -> None:
        home = _home(tmp_path)
        result = _invoke(
            home,
            [
                "alerts",
                "create",
                "redmi",
                "--max-price",
                "1700",
                "--label",
                "promo\n[bold red]FALSA[/bold red]",
            ],
        )
        assert result.exit_code == 2
        assert "controle" in result.output.lower()

    def test_label_longo_demais_e_recusado(self, tmp_path: Path) -> None:
        home = _home(tmp_path)
        result = _invoke(
            home,
            [
                "alerts",
                "create",
                "redmi",
                "--max-price",
                "1700",
                "--label",
                "x" * 201,
            ],
        )
        assert result.exit_code == 2

    def test_rate_limit_de_notificacoes_por_hora(self, tmp_path: Path) -> None:
        home = _home(tmp_path)
        _write_config(home, "[notifications]\nmax_per_hour = 1\n")

        for index in range(2):
            created = _invoke(
                home,
                [
                    "--json",
                    "alerts",
                    "create",
                    "redmi",
                    "--label",
                    f"alerta {index}",
                    "--max-price",
                    "1700",
                ],
            )
            assert created.exit_code == 0, created.output

        checked = _invoke(home, ["--json", "alerts", "check", "--source", "fixture"])
        assert checked.exit_code == 0, checked.output
        outcomes = json.loads(checked.output)["outcomes"]
        assert len(outcomes) == 2
        assert outcomes[0]["channels"][0]["ok"] is True
        assert outcomes[1]["channels"][0]["ok"] is False
        assert "limite" in outcomes[1]["channels"][0]["error"]

        with closing(sqlite3.connect(_db_path(home))) as connection:
            count = connection.execute("SELECT COUNT(*) FROM notification").fetchone()[0]
        assert count == 1

    def test_falha_de_canal_nao_derruba_alerta(self, tmp_path: Path, monkeypatch) -> None:
        from dealhunter.adapters.notify.base import NotificationError, NotificationMessage, Notifier

        class Boom:
            id = "email"
            label = "E-mail"

            def send(self, _message: NotificationMessage) -> None:
                raise NotificationError("falha ao enviar e-mail (SMTPAuthenticationError)")

        monkeypatch.setattr(
            "dealhunter.cli.wiring.build_notifier",
            lambda *_args, **_kwargs: (Notifier({"email": Boom()}), []),
        )
        home = _home(tmp_path)
        created = _invoke(
            home,
            [
                "--json",
                "alerts",
                "create",
                "redmi",
                "--max-price",
                "1700",
                "--channel",
                "email",
            ],
        )
        assert created.exit_code == 0, created.output

        checked = _invoke(home, ["--json", "alerts", "check", "--source", "fixture"])
        assert checked.exit_code == 0, checked.output
        outcome = json.loads(checked.output)["outcomes"][0]
        assert outcome["matched"] is True
        assert outcome["channels"][0]["ok"] is False
        assert "NotificationError" in outcome["channels"][0]["error"]

    def test_deduplicacao_impede_reenvio(self, tmp_path: Path) -> None:
        home = _home(tmp_path)
        created = _invoke(
            home,
            ["--json", "alerts", "create", "redmi", "--max-price", "1700"],
        )
        assert created.exit_code == 0, created.output

        first = _invoke(home, ["--json", "alerts", "check", "--source", "fixture"])
        second = _invoke(home, ["--json", "alerts", "check", "--source", "fixture"])
        assert first.exit_code == 0
        assert second.exit_code == 0

        second_outcome = json.loads(second.output)["outcomes"][0]
        assert second_outcome["channels"] == []
        assert "já notificado" in second_outcome["note"]

    def test_opt_out_por_pausa_interrompe_notificacoes(self, tmp_path: Path) -> None:
        home = _home(tmp_path)
        created = _invoke(home, ["--json", "alerts", "create", "redmi", "--max-price", "1700"])
        alert_id = json.loads(created.output)["alert_id"]

        paused = _invoke(home, ["--json", "alerts", "pause", str(alert_id)])
        assert paused.exit_code == 0

        checked = _invoke(home, ["--json", "alerts", "check", "--source", "fixture"])
        assert json.loads(checked.output)["outcomes"] == []


class TestPrivacy:
    def test_homes_diferentes_nao_misturam_alertas(self, tmp_path: Path) -> None:
        first_home = _home(tmp_path, "user-a")
        second_home = _home(tmp_path, "user-b")

        created = _invoke(
            first_home,
            ["--json", "alerts", "create", "redmi do usuario A", "--max-price", "1700"],
        )
        assert created.exit_code == 0, created.output

        other = _invoke(second_home, ["--json", "alerts", "list"])
        assert other.exit_code == 0
        assert json.loads(other.output)["alerts"] == []

    def test_delete_remove_eventos_e_notificacoes(self, tmp_path: Path) -> None:
        home = _home(tmp_path)
        created = _invoke(home, ["--json", "alerts", "create", "redmi", "--max-price", "1700"])
        alert_id = json.loads(created.output)["alert_id"]

        checked = _invoke(home, ["--json", "alerts", "check", "--source", "fixture"])
        assert checked.exit_code == 0

        with closing(sqlite3.connect(_db_path(home))) as connection:
            assert connection.execute("SELECT COUNT(*) FROM alert_event").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM notification").fetchone()[0] == 1

        deleted = _invoke(home, ["--json", "alerts", "delete", str(alert_id)])
        assert deleted.exit_code == 0

        with closing(sqlite3.connect(_db_path(home))) as connection:
            assert connection.execute("SELECT COUNT(*) FROM alert").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM alert_event").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM notification").fetchone()[0] == 0

    def test_destino_de_notificacao_nao_e_persistido(self, tmp_path: Path) -> None:
        home = _home(tmp_path)
        _invoke(home, ["alerts", "create", "redmi", "--max-price", "1700"])
        _invoke(home, ["alerts", "check", "--source", "fixture"])

        with closing(sqlite3.connect(_db_path(home))) as connection:
            row = connection.execute("SELECT destination FROM notification").fetchone()
        assert row is not None
        assert row[0] is None

    def test_debug_nao_expoe_email_configurado(self, tmp_path: Path) -> None:
        home = _home(tmp_path)
        _write_config(
            home,
            "\n".join(
                [
                    "[notifications]",
                    'email_from = "contato@example.com"',
                    'email_to = "joao.silva@example.com"',
                    'smtp_host = "smtp.example.com"',
                    "",
                ]
            ),
        )
        result = _invoke(home, ["--debug", "status"])
        assert result.exit_code == 0
        assert "joao.silva@example.com" not in result.output
