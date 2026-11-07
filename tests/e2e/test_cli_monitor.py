"""Testes ponta a ponta do comando ``monitor``."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from typer.testing import CliRunner

from dealhunter.adapters.storage.lock import FileLock
from dealhunter.cli.app import app
from dealhunter.runtime.paths import resolve_paths

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _flat(text: str) -> str:
    """Compara ignorando ANSI, quebras de linha e espaços de painéis Rich."""
    return "".join(_ANSI_RE.sub("", text).split()).lower()


def _home(tmp_path: Path) -> Path:
    return tmp_path / "home"


def _invoke(tmp_path: Path, args: list[str], *, env: dict[str, str] | None = None):
    full_env = {"DEALHUNTER_HOME": str(_home(tmp_path))}
    full_env.update(env or {})
    return runner.invoke(app, args, env=full_env)


def _write_config(tmp_path: Path, body: str) -> None:
    config_file = _home(tmp_path) / "config" / "config.toml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(body, encoding="utf-8")


def _create_alert(tmp_path: Path) -> int:
    created = _invoke(
        tmp_path,
        ["--json", "alerts", "create", "Redmi Note 14 256GB", "--max-price", "999999"],
    )
    assert created.exit_code == 0, created.output
    return int(json.loads(created.output)["alert_id"])


class TestMonitorOnce:
    def test_ciclo_unico_notifica_e_persiste_estado(self, tmp_path: Path) -> None:
        alert_id = _create_alert(tmp_path)

        result = _invoke(
            tmp_path,
            ["--json", "monitor", "--once", "--source", "fixture", "--ignore-quiet-hours"],
        )
        assert result.exit_code == 0, result.output

        payload = json.loads(result.output)
        assert payload["command"] == "monitor"
        assert payload["status"] == "ok"
        assert payload["trigger"] == "once"
        assert payload["previous_run"] is None
        assert payload["totals"]["checked"] == 1
        assert payload["totals"]["matched"] == 1
        assert payload["totals"]["notifications"] == 1
        assert len(payload["cycles"]) == 1

        cycle = payload["cycles"][0]
        assert cycle["status"] == "ok"
        assert cycle["outcomes"][0]["alert_id"] == alert_id
        outcome = cycle["outcomes"][0]
        assert outcome["matched"] is True
        assert outcome["channels"][0]["ok"] is True
        # Todo fato numérico expõe a procedência da coleta.
        assert outcome["source"] == "fixture"
        assert outcome["source_url"].startswith("https://")
        assert outcome["offer_url"].startswith("https://")
        assert outcome["collected_at"] is not None
        assert 0.0 <= outcome["confidence"] <= 1.0

    def test_segundo_ciclo_respeita_cooldown(self, tmp_path: Path) -> None:
        _create_alert(tmp_path)
        args = [
            "--json",
            "monitor",
            "--once",
            "--source",
            "fixture",
            "--ignore-quiet-hours",
        ]
        first = _invoke(tmp_path, args)
        assert first.exit_code == 0, first.output

        second = _invoke(tmp_path, args)
        assert second.exit_code == 0, second.output
        payload = json.loads(second.output)
        assert payload["previous_run"] is not None
        assert payload["totals"]["checked"] == 0
        assert payload["totals"]["skipped_cooldown"] == 1
        assert payload["cycles"][0]["status"] == "ok"

    def test_varios_ciclos_com_intervalo_zero(self, tmp_path: Path) -> None:
        _create_alert(tmp_path)

        result = _invoke(
            tmp_path,
            [
                "--json",
                "monitor",
                "--cycles",
                "2",
                "--interval",
                "0",
                "--source",
                "fixture",
                "--ignore-quiet-hours",
            ],
        )
        assert result.exit_code == 0, result.output

        payload = json.loads(result.output)
        assert len(payload["cycles"]) == 2
        assert payload["totals"]["checked"] == 1
        assert payload["totals"]["matched"] == 1
        assert payload["totals"]["skipped_cooldown"] == 1

    def test_quiet_hours_pula_ciclo(self, tmp_path: Path) -> None:
        now = datetime.now(UTC)
        start = (now - timedelta(hours=1)).strftime("%H:%M")
        end = (now + timedelta(hours=1)).strftime("%H:%M")
        _write_config(
            tmp_path,
            f"""
[general]
timezone = "UTC"

[monitor]
quiet_hours_start = "{start}"
quiet_hours_end = "{end}"
""",
        )

        result = _invoke(tmp_path, ["--json", "monitor", "--once", "--source", "fixture"])
        assert result.exit_code == 0, result.output

        payload = json.loads(result.output)
        assert payload["status"] == "quiet"
        assert payload["totals"]["checked"] == 0
        assert "quiet hours" in payload["cycles"][0]["note"]

    def test_ignore_quiet_hours_executa(self, tmp_path: Path) -> None:
        now = datetime.now(UTC)
        start = (now - timedelta(hours=1)).strftime("%H:%M")
        end = (now + timedelta(hours=1)).strftime("%H:%M")
        _write_config(
            tmp_path,
            f"""
[general]
timezone = "UTC"

[monitor]
quiet_hours_start = "{start}"
quiet_hours_end = "{end}"
""",
        )
        _create_alert(tmp_path)

        result = _invoke(
            tmp_path,
            ["--json", "monitor", "--once", "--source", "fixture", "--ignore-quiet-hours"],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "ok"
        assert payload["totals"]["checked"] == 1


class TestMonitorContract:
    def test_json_exige_execucao_finita(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["--json", "monitor", "--source", "fixture"])
        assert result.exit_code == 2
        assert "--once" in _flat(result.output) or "--cycles" in _flat(result.output)

    def test_once_e_cycles_sao_exclusivos(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["monitor", "--once", "--cycles", "2", "--source", "fixture"])
        assert result.exit_code == 2
        assert "não os dois" in result.output or "nao os dois" in result.output

    def test_saida_humana_mostra_resumo(self, tmp_path: Path) -> None:
        _create_alert(tmp_path)

        result = _invoke(
            tmp_path,
            ["monitor", "--once", "--source", "fixture", "--ignore-quiet-hours"],
        )
        assert result.exit_code == 0, result.output
        assert "Redmi" in result.output
        assert "ciclo(s)" in result.output

    def test_quiet_suprime_resumo_em_modo_quiet(self, tmp_path: Path) -> None:
        _create_alert(tmp_path)

        result = _invoke(
            tmp_path,
            [
                "--quiet",
                "monitor",
                "--once",
                "--source",
                "fixture",
                "--ignore-quiet-hours",
            ],
        )
        assert result.exit_code == 0, result.output
        assert result.output.strip() == ""

    def test_lock_impede_segunda_instancia(self, tmp_path: Path) -> None:
        paths = resolve_paths({"DEALHUNTER_HOME": str(_home(tmp_path))})
        paths.ensure_directories()
        lock = FileLock(paths.lock_file)
        lock.acquire()
        try:
            result = _invoke(
                tmp_path,
                ["--json", "monitor", "--once", "--source", "fixture"],
            )
        finally:
            lock.release()

        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["status"] == "locked"
        assert payload["locked"] is True
        assert "outra instância" in payload["error"]

    def test_erro_isolado_de_fonte_nao_vaza_traceback(self, tmp_path: Path) -> None:
        result = _invoke(
            tmp_path,
            ["--json", "monitor", "--once", "--source", "fonte-inexistente"],
        )
        # Fonte desconhecida é erro de uso, nunca traceback bruto.
        assert result.exit_code == 2
        assert "fonte desconhecida" in result.output.lower()
        assert "Traceback" not in result.output
