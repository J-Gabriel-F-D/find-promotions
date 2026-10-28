"""Segurança da configuração: PII, segredos, permissões e erros."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dealhunter.cli.app import app
from dealhunter.runtime.config import (
    AppConfig,
    load_config,
    mask_config_pii,
)
from dealhunter.runtime.container import build_runtime

runner = CliRunner()


def _invoke(tmp_path: Path, args: list[str], *, env: dict[str, str] | None = None):
    base_env = {"DEALHUNTER_HOME": str(tmp_path / "home")}
    base_env.update(env or {})
    return runner.invoke(app, args, env=base_env)


def _config_with_notifications(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "[notifications]",
                'email_from = "contato@dealhunter.example"',
                'email_to = "joao.silva@example.com"',
                'smtp_host = "smtp.example.com"',
                'smtp_user = "usuario.sensivel@example.com"',
                "",
            ]
        ),
        encoding="utf-8",
    )


class TestConfigMasking:
    def test_mask_config_pii_preserva_original(self) -> None:
        config = AppConfig.model_validate(
            {
                "notifications": {
                    "email_from": "contato@example.com",
                    "email_to": "joao.silva@example.com",
                    "smtp_user": "joao.silva",
                }
            }
        )
        masked = mask_config_pii(config)

        assert config.notifications.email_to == "joao.silva@example.com"
        assert masked.notifications.email_to == "j***@example.com"
        assert masked.notifications.email_from == "c***@example.com"
        assert masked.notifications.smtp_user == "j***"

    def test_mask_config_remove_segredos_de_url_de_feed(self) -> None:
        config = AppConfig.model_validate(
            {
                "sources": {
                    "feed_urls": [
                        "https://user:pass@feed.example/ofertas?token=segredo&key=abc#frag",
                        "https://feed.example/ofertas-sem-query",
                    ]
                }
            }
        )
        masked = mask_config_pii(config)

        assert masked.sources.feed_urls[0] == "https://feed.example/ofertas?***"
        assert masked.sources.feed_urls[1] == "https://feed.example/ofertas-sem-query"
        assert "segredo" not in str(masked.sources.feed_urls)
        assert "pass@" not in str(masked.sources.feed_urls)

    def test_config_show_json_mascara_pii(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        _config_with_notifications(home / "config" / "config.toml")

        result = _invoke(tmp_path, ["--json", "config", "show"])
        assert result.exit_code == 0, result.output
        output = result.output
        assert "joao.silva@example.com" not in output
        assert "usuario.sensivel@example.com" not in output
        assert "contato@dealhunter.example" not in output

        notifications = json.loads(output)["config"]["notifications"]
        assert notifications["email_to"] == "j***@example.com"
        assert notifications["email_from"] == "c***@dealhunter.example"

    def test_config_show_toml_mascara_pii(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        _config_with_notifications(home / "config" / "config.toml")

        result = _invoke(tmp_path, ["config", "show"])
        assert result.exit_code == 0, result.output
        assert "joao.silva@example.com" not in result.output
        assert "j***@example.com" in result.output

    def test_status_nao_expoe_email(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        _config_with_notifications(home / "config" / "config.toml")

        result = _invoke(tmp_path, ["--json", "status"])
        assert result.exit_code == 0, result.output
        assert "joao.silva@example.com" not in result.output
        assert "usuario.sensivel" not in result.output


class TestSecrets:
    def test_senha_em_variavel_de_ambiente_nao_aparece_na_saida(self, tmp_path: Path) -> None:
        result = _invoke(
            tmp_path,
            ["--json", "config", "show"],
            env={"DEALHUNTER_SMTP_PASSWORD": "hunter2-super-secreto"},
        )
        assert result.exit_code == 0, result.output
        assert "hunter2-super-secreto" not in result.output
        # A configuração guarda apenas o NOME da variável, nunca o valor.
        assert "DEALHUNTER_SMTP_PASSWORD" in result.output

    def test_chaves_desconhecidas_com_segredo_nao_sao_serializadas(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        config_file = home / "config" / "config.toml"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(
            "\n".join(
                [
                    "[notifications]",
                    'password = "nao-deveria-existir"',
                    'access_token = "abc123"',
                    'api_key = "sk-live-999"',
                    "",
                ]
            ),
            encoding="utf-8",
        )

        result = _invoke(tmp_path, ["--json", "config", "show"])
        assert result.exit_code == 0, result.output
        for secret in ("nao-deveria-existir", "abc123", "sk-live-999"):
            assert secret not in result.output

    def test_config_invalido_nao_ecoa_valor_sensivel(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        home.mkdir()
        config_file = home / "config" / "config.toml"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text('[general]\nlog_level = "TOKEN=super-secreto"\n', encoding="utf-8")

        result = _invoke(tmp_path, ["status"])
        assert result.exit_code == 6
        assert "super-secreto" not in result.output
        assert "TOKEN=" not in result.output

    def test_config_inexistente_falha_sem_traceback(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["--config", str(tmp_path / "nao-existe.toml"), "status"])
        assert result.exit_code == 6
        assert "não encontrado" in result.output
        assert "Traceback" not in result.output

    def test_caminho_com_markup_nao_e_interpretado(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["--config", "[red]nao-existe[/red]", "status"])
        assert result.exit_code == 6
        assert "Traceback" not in result.output
        assert "Erro de configuração" in result.output

    def test_load_config_nao_le_segredo_do_ambiente_para_o_modelo(self, isolated_home) -> None:
        result = load_config(
            isolated_home,
            environ={"DEALHUNTER_SMTP_PASSWORD": "hunter2"},
        )
        dumped = result.config.model_dump_json()
        assert "hunter2" not in dumped


class TestFilePermissions:
    @pytest.mark.skipif(os.name == "nt", reason="chmod não representa ACL no Windows")
    def test_diretorios_criados_sao_privados(self, isolated_home) -> None:
        for directory in (
            isolated_home.config_dir,
            isolated_home.data_dir,
            isolated_home.cache_dir,
            isolated_home.log_dir,
        ):
            assert directory.stat().st_mode & 0o777 == 0o700

    @pytest.mark.skipif(os.name == "nt", reason="chmod não representa ACL no Windows")
    def test_banco_criado_e_privado(self, tmp_path: Path) -> None:
        runtime = build_runtime(
            flags=None,
            environ={"DEALHUNTER_HOME": str(tmp_path / "home")},
        )
        runtime.database.migrate()
        assert runtime.database.path.stat().st_mode & 0o777 == 0o600
