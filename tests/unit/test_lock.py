"""Testes do lock exclusivo usado pelo monitor."""

from __future__ import annotations

from pathlib import Path

import pytest

from dealhunter.adapters.storage.lock import FileLock, LockUnavailable


def test_lock_exclusivo_e_liberado_ao_sair(tmp_path: Path) -> None:
    path = tmp_path / "monitor.lock"

    with FileLock(path) as lock:
        assert lock.locked is True
        assert path.exists()

        second = FileLock(path)
        with pytest.raises(LockUnavailable):
            second.acquire()

    assert not lock.locked
    assert "pid=" in path.read_text(encoding="ascii")
    third = FileLock(path)
    third.acquire()
    third.release()
    assert not third.locked


def test_release_e_idempotente(tmp_path: Path) -> None:
    lock = FileLock(tmp_path / "monitor.lock")
    lock.release()
    lock.acquire()
    lock.release()
    lock.release()
    assert not lock.locked


def test_acquire_repetido_nao_duplica_estado(tmp_path: Path) -> None:
    lock = FileLock(tmp_path / "monitor.lock")
    lock.acquire()
    lock.acquire()
    assert lock.locked
    lock.release()
    assert not lock.locked
