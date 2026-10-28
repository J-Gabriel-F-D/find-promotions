"""Redação de PII e credenciais em logs, erros e mensagens."""

from __future__ import annotations

import io
import logging
from pathlib import Path

import pytest

from dealhunter.runtime.logging import configure_logging, redact_text


class TestRedactText:
    def test_mascara_email(self) -> None:
        assert redact_text("contato: joao.silva@example.com") == "contato: j***@example.com"

    @pytest.mark.parametrize(
        "phone",
        [
            "+55 (11) 99999-9999",
            "+55 11 99999-9999",
            "11 99999-9999",
            "11999999999",
        ],
    )
    def test_mascara_telefone(self, phone: str) -> None:
        result = redact_text(f"telefone {phone}")
        assert phone not in result
        assert "***" in result

    @pytest.mark.parametrize(
        "secret",
        [
            "password=hunter2",
            "PASSWORD: hunter2",
            "token=abc123",
            "api_key=sk-live-123",
            "access_token=xyz",
            "Authorization: Bearer abc.def.ghi",
        ],
    )
    def test_mascara_atribuicao_de_segredo(self, secret: str) -> None:
        result = redact_text(f"config {secret}")
        assert "hunter2" not in result
        assert "abc123" not in result
        assert "sk-live-123" not in result
        assert "abc.def.ghi" not in result

    def test_nao_confunde_preco_com_telefone(self) -> None:
        text = "Preço R$ 1.649,00 em 2026-03-15T12:00:00Z"
        assert redact_text(text) == text

    def test_texto_sem_pii_fica_intacto(self) -> None:
        text = "Xiaomi Redmi Note 14 256GB por R$ 1.649,00"
        assert redact_text(text) == text


class TestStructuredLogs:
    def test_log_de_campos_sensiveis_e_mascarado(self, tmp_path: Path) -> None:
        stream = io.StringIO()
        log_file = tmp_path / "dealhunter.log"
        logger = configure_logging(
            level="debug", json_console=True, log_file=log_file, stream=stream
        )

        logger.error(
            "falha de envio",
            email="joao.silva@example.com",
            password="hunter2",
            phone="+55 (11) 99999-9999",
            note="token=abc123",
        )
        for handler in logging.getLogger().handlers:
            handler.flush()

        console = stream.getvalue()
        persisted = log_file.read_text(encoding="utf-8")
        for output in (console, persisted):
            assert "joao.silva@example.com" not in output
            assert "hunter2" not in output
            assert "99999-9999" not in output
            assert "abc123" not in output
            assert "***" in output

    def test_excecao_tambem_e_redigida(self, tmp_path: Path) -> None:
        stream = io.StringIO()
        log_file = tmp_path / "dealhunter.log"
        logger = configure_logging(
            level="debug", json_console=True, log_file=log_file, stream=stream
        )

        try:
            raise RuntimeError("password=hunter2 token=abc123 email=joao@example.com")
        except RuntimeError:
            logger.error("erro inesperado", exc_info=True)
        for handler in logging.getLogger().handlers:
            handler.flush()

        output = stream.getvalue() + log_file.read_text(encoding="utf-8")
        assert "hunter2" not in output
        assert "abc123" not in output
        assert "joao@example.com" not in output

    def test_arquivo_de_log_restrito_no_posix(self, tmp_path: Path) -> None:
        import os

        if os.name == "nt":
            pytest.skip("ACL do Windows não é representada por chmod")
        stream = io.StringIO()
        log_file = tmp_path / "dealhunter.log"
        configure_logging(level="info", log_file=log_file, stream=stream)
        mode = log_file.stat().st_mode & 0o777
        assert mode == 0o600
