"""PID file e verificação de processos usados pelo monitor em segundo plano."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from dealhunter.runtime.process import (
    _linux_process_is_zombie,
    _stat_is_zombie,
    clear_pid,
    pid_running,
    read_pid,
    terminate_pid,
    write_pid,
)


def test_write_read_e_clear_do_pid(tmp_path: Path) -> None:
    path = tmp_path / "monitor.pid"

    write_pid(path, os.getpid())

    assert read_pid(path) == os.getpid()
    assert pid_running(os.getpid()) is True
    assert clear_pid(path, expected_pid=os.getpid() + 1) is False
    assert path.exists()
    assert clear_pid(path, expected_pid=os.getpid()) is True
    assert not path.exists()
    assert clear_pid(path) is False


def test_pid_invalido_ou_ausente_devolve_none(tmp_path: Path) -> None:
    path = tmp_path / "monitor.pid"

    assert read_pid(path) is None
    path.write_text("nao-e-pid", encoding="ascii")
    assert read_pid(path) is None
    path.write_text("-1", encoding="ascii")
    assert read_pid(path) is None
    path.write_text("0", encoding="ascii")
    assert read_pid(path) is None
    path.write_text("1" * 21, encoding="ascii")
    assert read_pid(path) is None


def test_pid_inexistente_nao_esta_rodando() -> None:
    # PID 0 nunca é um processo comum e é recusado antes de qualquer syscall.
    assert pid_running(0) is False
    assert terminate_pid(0) is False


def test_arquivo_do_pid_e_privado(tmp_path: Path) -> None:
    path = tmp_path / "monitor.pid"
    write_pid(path, os.getpid())

    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


def test_estado_zumbi_em_proc_stat() -> None:
    assert _stat_is_zombie("123 (python) Z 1 2 3") is True
    assert _stat_is_zombie("123 (python) S 1 2 3") is False
    assert _stat_is_zombie("123 (com (parenteses)) Z 1") is True
    assert _stat_is_zombie("sem-formato") is False


def test_processo_zumbi_nao_conta_como_rodando() -> None:
    if not sys.platform.startswith("linux"):
        pytest.skip("detecção de zumbi usa /proc do Linux")

    pid = os.fork()
    if pid == 0:  # pragma: no cover - ramo do processo filho
        os._exit(0)
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not _linux_process_is_zombie(pid):
            time.sleep(0.01)
        assert _linux_process_is_zombie(pid) is True
        assert pid_running(pid) is False
    finally:
        os.waitpid(pid, 0)
