"""PID file e ciclo de vida do monitor em segundo plano.

O PID file é um detalhe operacional: não contém dados do usuário e serve para
``monitor --stop`` e diagnóstico. A existência de um PID não prova que o
processo é o monitor; por isso o comando ``--stop`` também confere o lock antes
de encerrar alguém.
"""

from __future__ import annotations

import ctypes
import os
import signal
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

from dealhunter.runtime.permissions import restrict_path

MAX_PID_CHARS = 20


def read_pid(path: Path) -> int | None:
    """Lê um PID válido; arquivo ausente, vazio ou corrompido devolve ``None``."""
    try:
        text = Path(path).read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return None
    if not text.isdigit() or len(text) > MAX_PID_CHARS:
        return None
    pid = int(text)
    return pid if pid > 0 else None


def write_pid(path: Path, pid: int) -> None:
    """Grava o PID de forma atômica e restringe a permissão do arquivo."""
    if pid <= 0:
        raise ValueError("PID inválido")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(f"{pid}\n")
        restrict_path(temporary, directory=False)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            with suppress(OSError):
                temporary.unlink()
    restrict_path(target, directory=False)


def clear_pid(path: Path, *, expected_pid: int | None = None) -> bool:
    """Remove o PID file; com ``expected_pid`` só remove se for o dono."""
    target = Path(path)
    if expected_pid is not None and read_pid(target) != expected_pid:
        return False
    try:
        target.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return True


def pid_running(pid: int) -> bool:
    """Diz se o processo existe, sem enviar sinal destrutivo."""
    if pid <= 0:
        return False
    if os.name == "nt":
        kernel32 = _kernel32()
        handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def terminate_pid(pid: int) -> bool:
    """Encerra o processo de forma graciosa no POSIX e forçada no Windows."""
    if pid <= 0:
        return False
    if os.name == "nt":
        kernel32 = _kernel32()
        handle = kernel32.OpenProcess(0x0001, False, pid)  # PROCESS_TERMINATE
        if not handle:
            return False
        try:
            return bool(kernel32.TerminateProcess(handle, 1))
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return False
    return True


def _kernel32() -> Any:
    # ``windll`` só existe no Windows; o cast mantém o mypy estrito feliz no CI
    # Linux, onde esta função nunca é chamada.
    return cast(Any, ctypes).windll.kernel32
