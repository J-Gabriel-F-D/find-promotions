"""Contatos por referência (``env:``/``keyring:``) sem PII em texto claro.

O TOML guarda apenas o *nome* da variável ou da entrada do cofre. O valor real
só é resolvido no momento de montar o canal e nunca aparece em ``config show``,
logs, avisos ou JSON de erro.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dealhunter.adapters.notify.registry import build_notifier
from dealhunter.cli.app import app
from dealhunter.runtime.config import AppConfig, NotificationSettings, mask_config_pii
from dealhunter.runtime.secrets import KEYRING_SERVICE, SecretStore, parse_reference

runner = CliRunner()
TOKEN = "tok_super_secreto_123"
PUBLIC_IP = "93.184.216.34"
PHONE = "+5511999999999"
EMAIL = "joao.silva@example.com"


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.values.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        self.values[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        self.values.pop((service_name, username), None)


@pytest.fixture()
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> FakeKeyring:
    backend = FakeKeyring()
    monkeypatch.setattr("dealhunter.runtime.secrets.load_keyring", lambda: backend)
    monkeypatch.delenv("DEALHUNTER_DISABLE_KEYRING", raising=False)
    return backend


def _invoke(home: Path, args: list[str], *, env: dict[str, str] | None = None):
    return runner.invoke(
        app,
        args,
        env={"DEALHUNTER_HOME": str(home), **(env or {})},
    )


def _public_resolver(_host: str, _port: int) -> list[str]:
    return [PUBLIC_IP]


def _write_config(home: Path, body: str) -> None:
    config_file = home / "config" / "config.toml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(body, encoding="utf-8")


class TestReferenceParsing:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("env:CONTATO_EMAIL", ("env", "CONTATO_EMAIL")),
            ("keyring:CONTATO_SMS", ("keyring", "CONTATO_SMS")),
            ("env:_PRIVADO1", ("env", "_PRIVADO1")),
            ("joao@example.com", None),
            ("+5511999999999", None),
            ("env:", None),
            ("env:1INVALIDO", None),
            ("keyring:nome com espaço", None),
            ("ENV:CONTATO_EMAIL", None),
            ("envx:CONTATO_EMAIL", None),
        ],
    )
    def test_parse_reference(self, value: str, expected: tuple[str, str] | None) -> None:
        assert parse_reference(value) == expected

    def test_resolve_nao_devolve_nome_bruto(self) -> None:
        store = SecretStore(environ={}, backend=FakeKeyring())

        assert store.resolve("env:AUSENTE") is None
        assert store.resolve("keyring:AUSENTE") is None
        # Um literal continua literal: não é confundido com referência.
        assert store.resolve(EMAIL) == EMAIL


class TestConfigReferences:
    def test_config_aceita_referencias(self) -> None:
        settings = NotificationSettings(
            email_to="env:CONTATO_EMAIL",
            sms_to="keyring:CONTATO_SMS",
            whatsapp_phone="env:CONTATO_WHATSAPP",
        )

        assert settings.email_to == "env:CONTATO_EMAIL"
        assert settings.sms_to == "keyring:CONTATO_SMS"
        assert settings.whatsapp_phone == "env:CONTATO_WHATSAPP"

    @pytest.mark.parametrize(
        "value",
        [
            "env:",
            "env:1INVALIDO",
            "keyring:nome com espaço",
            "keyring:",
            "env:CONTATO\x01",
        ],
    )
    def test_config_recusa_referencia_malformada(self, value: str) -> None:
        with pytest.raises(ValueError):
            NotificationSettings(email_to=value)

    def test_mask_config_oculta_origem_e_nome(self) -> None:
        config = AppConfig.model_validate(
            {
                "notifications": {
                    "email_to": "env:CONTATO_EMAIL",
                    "sms_to": "keyring:CONTATO_SMS",
                    "sms_from": "env:REMETENTE_SMS",
                }
            }
        )
        masked = mask_config_pii(config)

        assert masked.notifications.email_to == "env:***"
        assert masked.notifications.sms_to == "keyring:***"
        assert masked.notifications.sms_from == "env:***"
        dumped = masked.model_dump_json()
        for name in ("CONTATO_EMAIL", "CONTATO_SMS", "REMETENTE_SMS"):
            assert name not in dumped

    def test_config_show_mascara_referencia_sem_resolver(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        _write_config(
            home,
            "\n".join(
                [
                    "[notifications]",
                    'email_to = "env:CONTATO_EMAIL"',
                    'sms_to = "keyring:CONTATO_SMS"',
                    'smtp_host = "smtp.example.com"',
                    "",
                ]
            ),
        )
        monkeypatch.setenv("CONTATO_EMAIL", EMAIL)

        result = _invoke(home, ["--json", "config", "show"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)["config"]["notifications"]
        assert payload["email_to"] == "env:***"
        assert payload["sms_to"] == "keyring:***"
        for secret in (EMAIL, "CONTATO_EMAIL", "CONTATO_SMS"):
            assert secret not in result.output

    def test_config_show_toml_nao_vaza_nome_da_referencia(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        _write_config(
            home,
            "\n".join(
                [
                    "[notifications]",
                    'email_to = "env:CONTATO_EMAIL"',
                    "",
                ]
            ),
        )
        monkeypatch.setenv("CONTATO_EMAIL", EMAIL)

        result = _invoke(home, ["config", "show"])

        assert result.exit_code == 0, result.output
        assert "env:***" in result.output
        assert EMAIL not in result.output
        assert "CONTATO_EMAIL" not in result.output


class TestNotifierReferences:
    def test_env_resolve_telefone_do_sms(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CONTATO_SMS", PHONE)
        monkeypatch.setenv("DEALHUNTER_SMS_TOKEN", TOKEN)
        settings = NotificationSettings(
            channels=["console", "sms"],
            sms_api_url="https://sms.example.com/v1/messages",
            sms_to="env:CONTATO_SMS",
        )

        notifier, warnings = build_notifier(
            settings,
            printer=lambda _text: None,
            environ={
                "CONTATO_SMS": PHONE,
                "DEALHUNTER_SMS_TOKEN": TOKEN,
            },
            resolver=_public_resolver,
        )

        assert notifier.supports("sms")
        assert warnings == []
        channel = notifier._channels["sms"]  # type: ignore[attr-defined]
        assert channel._to == PHONE  # type: ignore[attr-defined]
        assert channel._to != "CONTATO_SMS"  # type: ignore[attr-defined]

    def test_keyring_resolve_email_sem_gravar_no_toml(self, fake_keyring: FakeKeyring) -> None:
        fake_keyring.values[(KEYRING_SERVICE, "REMETENTE")] = "site@example.com"
        fake_keyring.values[(KEYRING_SERVICE, "CONTATO_EMAIL")] = EMAIL
        store = SecretStore(environ={}, backend=fake_keyring)
        settings = NotificationSettings(
            channels=["console", "email"],
            smtp_host="smtp.example.com",
            email_from="keyring:REMETENTE",
            email_to="keyring:CONTATO_EMAIL",
        )

        notifier, warnings = build_notifier(
            settings,
            printer=lambda _text: None,
            secrets=store,
        )

        assert notifier.supports("email")
        assert warnings == []
        channel = notifier._channels["email"]  # type: ignore[attr-defined]
        assert channel._default_recipient == EMAIL  # type: ignore[attr-defined]
        assert channel._sender == "site@example.com"  # type: ignore[attr-defined]

    def test_referencia_ausente_nao_registra_canal_nem_ecoa_nome(self) -> None:
        settings = NotificationSettings(
            channels=["console", "sms"],
            sms_api_url="https://sms.example.com/v1/messages",
            sms_to="env:CONTATO_SMS",
        )

        notifier, warnings = build_notifier(
            settings,
            printer=lambda _text: None,
            environ={"DEALHUNTER_SMS_TOKEN": TOKEN},
            resolver=_public_resolver,
        )

        assert not notifier.supports("sms")
        joined = " ".join(warnings)
        assert "sms_to" in joined
        assert "CONTATO_SMS" not in joined
        assert PHONE not in joined


class TestPrivacyReferences:
    def test_export_sem_opt_in_mascara_referencia(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        _write_config(
            home,
            "\n".join(
                [
                    "[notifications]",
                    'email_to = "env:CONTATO_EMAIL"',
                    "",
                ]
            ),
        )
        monkeypatch.setenv("CONTATO_EMAIL", EMAIL)

        result = _invoke(home, ["--json", "privacy", "export"])

        assert result.exit_code == 0, result.output
        profile = json.loads(result.output)["profile"]["notifications"]
        assert profile["email_to"] == "env:***"
        assert EMAIL not in result.output
        assert "CONTATO_EMAIL" not in result.output

    def test_export_com_opt_in_resolve_env(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        home = tmp_path / "home"
        _write_config(
            home,
            "\n".join(
                [
                    "[notifications]",
                    'email_to = "env:CONTATO_EMAIL"',
                    "",
                ]
            ),
        )
        monkeypatch.setenv("CONTATO_EMAIL", EMAIL)

        result = _invoke(home, ["--json", "privacy", "export", "--include-contacts"])

        assert result.exit_code == 0, result.output
        profile = json.loads(result.output)["profile"]["notifications"]
        assert profile["email_to"] == EMAIL

    def test_export_com_opt_in_resolve_keyring(
        self, tmp_path: Path, fake_keyring: FakeKeyring
    ) -> None:
        home = tmp_path / "home"
        _write_config(
            home,
            "\n".join(
                [
                    "[notifications]",
                    'email_to = "keyring:CONTATO_EMAIL"',
                    "",
                ]
            ),
        )
        fake_keyring.values[(KEYRING_SERVICE, "CONTATO_EMAIL")] = EMAIL

        result = _invoke(home, ["--json", "privacy", "export", "--include-contacts"])

        assert result.exit_code == 0, result.output
        profile = json.loads(result.output)["profile"]["notifications"]
        assert profile["email_to"] == EMAIL
