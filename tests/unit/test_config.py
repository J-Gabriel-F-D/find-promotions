"""Testes de carga e precedencia de configuracao."""

from __future__ import annotations

from pathlib import Path

import pytest

from dealhunter.runtime.config import AppConfig, ConfigError, dump_config_toml, load_config
from dealhunter.runtime.paths import AppPaths


def test_defaults(isolated_home: AppPaths) -> None:
    result = load_config(isolated_home, environ={})
    assert result.config.general.currency == "BRL"
    assert result.config.general.results_limit == 20
    assert result.config.ai.enabled is False
    assert result.config.sources.respect_robots is True
    assert result.files_read == ()


def test_arquivo_do_usuario_sobrepoe_defaults(isolated_home: AppPaths) -> None:
    isolated_home.config_file.write_text(
        '[general]\nresults_limit = 5\ncurrency = "USD"\n', encoding="utf-8"
    )
    result = load_config(isolated_home, environ={})
    assert result.config.general.results_limit == 5
    assert result.config.general.currency == "USD"
    assert result.config.general.language == "pt-BR"
    assert isolated_home.config_file in result.files_read


def test_env_sobrepoe_arquivo(isolated_home: AppPaths) -> None:
    isolated_home.config_file.write_text("[general]\nresults_limit = 5\n", encoding="utf-8")
    result = load_config(isolated_home, environ={"DEALHUNTER_GENERAL__RESULTS_LIMIT": "7"})
    assert result.config.general.results_limit == 7


def test_env_converte_booleanos_e_listas(isolated_home: AppPaths) -> None:
    result = load_config(
        isolated_home,
        environ={
            "DEALHUNTER_AI__ENABLED": "true",
            "DEALHUNTER_SOURCES__ENABLED": '["mercadolivre", "fixture"]',
        },
    )
    assert result.config.ai.enabled is True
    assert result.config.sources.enabled == ["mercadolivre", "fixture"]


def test_config_explicita_tem_precedencia(isolated_home: AppPaths, tmp_path: Path) -> None:
    isolated_home.config_file.write_text("[general]\nresults_limit = 5\n", encoding="utf-8")
    explicit = tmp_path / "custom.toml"
    explicit.write_text("[general]\nresults_limit = 9\n", encoding="utf-8")

    result = load_config(isolated_home, explicit_path=explicit, environ={})
    assert result.config.general.results_limit == 9
    assert result.files_read == (explicit,)


def test_config_explicita_inexistente_falha(isolated_home: AppPaths, tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(isolated_home, explicit_path=tmp_path / "nope.toml", environ={})


def test_valor_invalido_gera_erro_amigavel(isolated_home: AppPaths) -> None:
    with pytest.raises(ConfigError) as excinfo:
        load_config(isolated_home, environ={"DEALHUNTER_GENERAL__RESULTS_LIMIT": "0"})
    assert "general.results_limit" in str(excinfo.value)


def test_toml_invalido_gera_erro_amigavel(isolated_home: AppPaths) -> None:
    isolated_home.config_file.write_text("[general\nresults_limit = 5", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(isolated_home, environ={})


def test_toml_com_bom_utf8_e_aceito(isolated_home: AppPaths) -> None:
    """Editores do Windows (Notepad, Set-Content) gravam BOM por padrao."""
    isolated_home.config_file.write_bytes("[general]\nresults_limit = 4\n".encode("utf-8-sig"))

    result = load_config(isolated_home, environ={})

    assert result.config.general.results_limit == 4


def test_dump_nao_contem_none_e_roundtrip() -> None:
    text = dump_config_toml(AppConfig())
    assert "None" not in text
    assert "[general]" in text
