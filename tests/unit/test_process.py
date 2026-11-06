"""PID file e verificação de processos usados pelo monitor em segundo plano."""

from __future__ import annotations

import os
from pathlib import Path

from dealhunter.runtime.process import (
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
