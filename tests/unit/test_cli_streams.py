"""Testes da configuração de streams (UTF-8 na saída)."""

from __future__ import annotations

import sys

from dealhunter.cli.app import _use_utf8_streams


class FakeStream:
    def __init__(self, encoding: str | None) -> None:
        self.encoding = encoding
        self.calls: list[dict[str, str]] = []

    def reconfigure(self, **kwargs: str) -> None:
        self.calls.append(kwargs)
        self.encoding = kwargs.get("encoding", self.encoding)


def test_forca_utf8_quando_codificacao_local(monkeypatch) -> None:
    out, err = FakeStream("cp1252"), FakeStream("cp850")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    _use_utf8_streams()

    assert out.encoding == "utf-8"
    assert err.encoding == "utf-8"
    assert out.calls[0]["errors"] == "strict"
    assert err.calls[0]["errors"] == "replace"


def test_nao_mexe_quando_ja_e_utf8(monkeypatch) -> None:
    out, err = FakeStream("utf-8"), FakeStream("UTF-8")
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    _use_utf8_streams()

    assert out.calls == []
    assert err.calls == []


def test_stream_sem_reconfigure_e_ignorado(monkeypatch) -> None:
    class SemReconfigure:
        encoding = "cp1252"

    out = SemReconfigure()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", SemReconfigure())

    _use_utf8_streams()  # não deve levantar
