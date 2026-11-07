"""Monitor em segundo plano: daemon, PID file, parada e limpeza."""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable
from pathlib import Path

from typer.testing import CliRunner

from dealhunter.adapters.storage.lock import FileLock, LockUnavailable
from dealhunter.cli.app import app
from dealhunter.runtime.paths import AppPaths, resolve_paths
from dealhunter.runtime.process import (
    clear_pid,
    pid_running,
    read_pid,
    terminate_pid,
    write_pid,
)

runner = CliRunner()


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def _flat(text: str) -> str:
    """Compara ignorando ANSI, quebras de linha e espaços de painéis Rich."""
    return "".join(_ANSI_RE.sub("", text).split()).lower()


def _invoke(tmp_path: Path, args: list[str]):
    return runner.invoke(app, args, env={"DEALHUNTER_HOME": str(tmp_path / "home")})


def _paths(tmp_path: Path) -> AppPaths:
    paths = resolve_paths({"DEALHUNTER_HOME": str(tmp_path / "home")})
    paths.ensure_directories()
    return paths


def _wait_for(predicate: Callable[[], bool], *, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _lock_busy(paths: AppPaths) -> bool:
    guard = FileLock(paths.lock_file)
    try:
        guard.acquire()
    except (LockUnavailable, OSError):
        return True
    else:
        guard.release()
        return False


class TestDaemonContract:
    def test_daemon_e_stop_sao_exclusivos(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["monitor", "--daemon", "--stop"])

        assert result.exit_code == 2
        assert _flat("não os dois") in _flat(result.output)

    def test_daemon_nao_combina_com_once(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["monitor", "--daemon", "--once"])

        assert result.exit_code == 2
        assert "--once" in _flat(result.output)

    def test_stop_nao_aceita_opcoes_de_execucao(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["monitor", "--stop", "--interval", "5"])

        assert result.exit_code == 2
        assert "--stop" in _flat(result.output)

    def test_stop_sem_monitor_e_idempotente(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["--json", "monitor", "--stop"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "not_running"
        assert payload["daemon"] is True

    def test_daemon_recusa_quando_pid_ja_esta_rodando(self, tmp_path: Path) -> None:
        paths = _paths(tmp_path)
        write_pid(paths.pid_file, os.getpid())
        try:
            result = _invoke(
                tmp_path,
                ["--json", "monitor", "--daemon", "--interval", "1", "--source", "fixture"],
            )

            assert result.exit_code == 1
            payload = json.loads(result.output)
            assert payload["status"] == "already_running"
            assert payload["pid"] == os.getpid()
            # O processo atual (o próprio teste) nunca é encerrado.
            assert pid_running(os.getpid()) is True
        finally:
            clear_pid(paths.pid_file, expected_pid=os.getpid())

    def test_stop_remove_pid_orfao_sem_matar_processo_reciclado(self, tmp_path: Path) -> None:
        paths = _paths(tmp_path)
        # PID de um processo vivo, mas sem o lock do monitor: é um PID antigo
        # reciclado, então --stop não deve enviar sinal.
        write_pid(paths.pid_file, os.getpid())

        result = _invoke(tmp_path, ["--json", "monitor", "--stop"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["status"] == "not_running"
        assert payload["stale_pid"] == os.getpid()
        assert not paths.pid_file.exists()
        assert pid_running(os.getpid()) is True

    def test_pid_corrompido_nao_impede_novo_daemon(self, tmp_path: Path) -> None:
        paths = _paths(tmp_path)
        paths.pid_file.write_text("nao-e-pid", encoding="ascii")

        result = _invoke(tmp_path, ["--json", "monitor", "--stop"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["status"] == "not_running"
        assert not paths.pid_file.exists()


class TestDaemonLifecycle:
    def test_inicia_em_segundo_plano_e_stop_encerra(self, tmp_path: Path) -> None:
        paths = _paths(tmp_path)
        pid: int | None = None
        try:
            started = _invoke(
                tmp_path,
                [
                    "--json",
                    "monitor",
                    "--daemon",
                    "--interval",
                    "1",
                    "--source",
                    "fixture",
                ],
            )
            assert started.exit_code == 0, started.output
            payload = json.loads(started.output)
            assert payload["status"] == "started"
            pid = int(payload["pid"])
            assert pid > 0
            assert Path(payload["pid_file"]) == paths.pid_file

            # Só encerramos com segurança depois que o filho mantém o lock.
            assert _wait_for(lambda: _lock_busy(paths))
            assert _wait_for(lambda: read_pid(paths.pid_file) is not None)
            recorded_pid = read_pid(paths.pid_file)
            assert recorded_pid is not None
            assert pid_running(recorded_pid) is True

            stopped = _invoke(tmp_path, ["--json", "monitor", "--stop"])
            assert stopped.exit_code == 0, stopped.output
            stopped_payload = json.loads(stopped.output)
            assert stopped_payload["status"] == "stopped"
            # Com shim do Windows, o PID real pode ser gravado pelo filho
            # depois que o pai já respondeu; o contrato é não sobrar monitor.
            stopped_pid = int(stopped_payload["pid"])
            assert stopped_pid > 0

            assert _wait_for(lambda: not pid_running(stopped_pid))
            assert _wait_for(lambda: not pid_running(recorded_pid))
            assert _wait_for(lambda: not pid_running(pid))
            assert _wait_for(lambda: not _lock_busy(paths))
            assert not paths.pid_file.exists()
        finally:
            candidates = {read_pid(paths.pid_file), pid}
            for candidate in candidates:
                if candidate is not None and pid_running(candidate):
                    terminate_pid(candidate)
            assert _wait_for(
                lambda: (
                    not any(
                        candidate is not None and pid_running(candidate) for candidate in candidates
                    )
                )
            )
            assert _wait_for(lambda: not _lock_busy(paths))
            clear_pid(paths.pid_file)

    def test_dois_daemons_nao_rodam_juntos(self, tmp_path: Path) -> None:
        paths = _paths(tmp_path)
        pid: int | None = None
        try:
            first = _invoke(
                tmp_path,
                ["--json", "monitor", "--daemon", "--interval", "1", "--source", "fixture"],
            )
            assert first.exit_code == 0, first.output
            pid = int(json.loads(first.output)["pid"])
            assert _wait_for(lambda: _lock_busy(paths))

            second = _invoke(
                tmp_path,
                ["--json", "monitor", "--daemon", "--interval", "1", "--source", "fixture"],
            )
            assert second.exit_code == 1
            assert json.loads(second.output)["status"] == "already_running"
        finally:
            candidates = {read_pid(paths.pid_file), pid}
            for candidate in candidates:
                if candidate is not None and pid_running(candidate):
                    terminate_pid(candidate)
            assert _wait_for(
                lambda: (
                    not any(
                        candidate is not None and pid_running(candidate) for candidate in candidates
                    )
                )
            )
            assert _wait_for(lambda: not _lock_busy(paths))
            clear_pid(paths.pid_file)
