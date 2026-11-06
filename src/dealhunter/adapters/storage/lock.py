"""Lock exclusivo de arquivo, multiplataforma.

O monitor não pode rodar duas vezes ao mesmo tempo na mesma máquina/usuário:
duas instâncias duplicariam buscas e poderiam competir pelas mesmas notificações.
O lock é mantido aberto durante toda a execução e liberado no fim, inclusive em
interrupção.

Implementação:
* POSIX: ``fcntl.flock`` não bloqueante.
* Windows: ``msvcrt.locking`` não bloqueante.

Não há dependência de terceiros e o arquivo de lock não contém segredos.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path
from types import TracebackType
from typing import Any


class LockUnavailable(RuntimeError):
    """Outra instância já mantém o lock."""


def _platform_module() -> Any:
    # Import dinâmico evita que o mypy/CI de um SO tente resolver o módulo do
    # outro. Os dois módulos fazem parte da biblioteca padrão.
    name = "msvcrt" if os.name == "nt" else "fcntl"
    return importlib.import_module(name)


class FileLock:
    """Lock exclusivo não bloqueante baseado em um arquivo local."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._handle: Any = None
        self._module = _platform_module()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def locked(self) -> bool:
        return self._handle is not None

    def acquire(self) -> None:
        if self._handle is not None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self._path, "a+b")  # noqa: SIM115 - fica aberto durante a execução

        try:
            if os.name == "nt":
                # msvcrt exige um byte existente no intervalo bloqueado.
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                self._module.locking(handle.fileno(), self._module.LK_NBLCK, 1)
            else:
                self._module.flock(handle.fileno(), self._module.LOCK_EX | self._module.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise LockUnavailable("outra instância do monitor já está em execução") from exc

        self._handle = handle
        self._write_owner()

    def _write_owner(self) -> None:
        """Grava apenas PID/host para diagnóstico; nunca dados do usuário."""
        if self._handle is None:
            return
        try:
            self._handle.seek(0)
            self._handle.truncate()
            self._handle.write(f"pid={os.getpid()}\n".encode("ascii"))
            self._handle.flush()
        except OSError:
            # Metadados são auxiliares: nunca invalidam um lock já adquirido.
            pass

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if os.name == "nt":
                handle.seek(0)
                self._module.locking(handle.fileno(), self._module.LK_UNLCK, 1)
            else:
                self._module.flock(handle.fileno(), self._module.LOCK_UN)
        except OSError:
            pass
        finally:
            handle.close()

    def __enter__(self) -> FileLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()
