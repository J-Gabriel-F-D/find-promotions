"""Segredos: precedência env/keyring, erros, CLI e ausência de vazamentos."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from dealhunter.adapters.notify.registry import build_notifier
from dealhunter.adapters.sources.registry import build_adapters
from dealhunter.cli.app import app
from dealhunter.runtime.config import NotificationSettings, SourcesSettings
from dealhunter.runtime.secrets import KEYRING_SERVICE, SecretStore

runner = CliRunner()


class FakeKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.get_calls = 0
        self.set_calls = 0
        self.delete_calls = 0

    def get_password(self, service_name: str, username: str) -> str | None:
        self.get_calls += 1
        return self.values.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        self.set_calls += 1
        self.values[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        self.delete_calls += 1
        if (service_name, username) not in self.values:
            raise KeyError("não encontrado")
        del self.values[(service_name, username)]


class ExplodingKeyring(FakeKeyring):
    def get_password(self, service_name: str, username: str) -> str | None:
        raise RuntimeError("falha interna com senha super-secreta")


@pytest.fixture()
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> FakeKeyring:
    backend = FakeKeyring()
    monkeypatch.setattr("dealhunter.runtime.secrets.load_keyring", lambda: backend)
    monkeypatch.delenv("DEALHUNTER_DISABLE_KEYRING", raising=False)
    return backend


def _invoke(home: Path, args: list[str], *, env: dict[str, str] | None = None, input: str = ""):
    return runner.invoke(
        app,
        args,
        env={"DEALHUNTER_HOME": str(home), **(env or {})},
        input=input,
    )


class TestSecretStore:
    def test_env_tem_precedencia_sobre_keyring(self) -> None:
        backend = FakeKeyring()
        backend.values[(KEYRING_SERVICE, "TOKEN")] = "do-keyring"
        store = SecretStore(environ={"TOKEN": "do-env"}, backend=backend)

        assert store.get("TOKEN") == "do-env"
        assert backend.get_calls == 0

    def test_keyring_e_fallback(self) -> None:
        backend = FakeKeyring()
        backend.values[(KEYRING_SERVICE, "TOKEN")] = "do-keyring"
        store = SecretStore(environ={}, backend=backend)

        assert store.get("TOKEN") == "do-keyring"
        assert store.source("TOKEN") == "keyring"

    def test_nome_invalido_nao_consulta_backend(self) -> None:
        backend = FakeKeyring()
        store = SecretStore(environ={}, backend=backend)

        assert store.get("../../etc/passwd") is None
        assert store.source("nome com espaço") is None
        assert backend.get_calls == 0

    def test_erro_do_backend_nao_vaza_nem_quebra(self) -> None:
        store = SecretStore(environ={}, backend=ExplodingKeyring())

        assert store.get("TOKEN") is None
        assert store.source("TOKEN") is None

    def test_erro_ao_gravar_nao_vaza_mensagem_do_backend(self) -> None:
        class WriteFail(FakeKeyring):
            def set_password(self, service_name: str, username: str, password: str) -> None:
                raise RuntimeError(f"falhou com {password}")

        store = SecretStore(environ={}, backend=WriteFail())
        with pytest.raises(RuntimeError) as captured:
            store.set("TOKEN", "segredo-que-nao-pode-vazar")

        assert "segredo-que-nao-pode-vazar" not in str(captured.value)
        assert "falha ao gravar" in str(captured.value)

    def test_set_e_delete(self) -> None:
        backend = FakeKeyring()
        store = SecretStore(environ={}, backend=backend)

        store.set("TOKEN", "segredo")
        assert store.get("TOKEN") == "segredo"
        assert store.delete("TOKEN") is True
        assert store.get("TOKEN") is None
        assert store.delete("TOKEN") is False

    def test_set_rejeita_valor_vazio_ou_com_controle(self) -> None:
        store = SecretStore(environ={}, backend=FakeKeyring())

        with pytest.raises(ValueError):
            store.set("TOKEN", "")
        with pytest.raises(ValueError):
            store.set("TOKEN", "linha\ninjetada")
        with pytest.raises(ValueError):
            store.set("nome inválido", "valor")

    def test_sem_backend_set_falha_e_delete_retorna_false(self) -> None:
        store = SecretStore(environ={}, backend=None)
        store._disable = True  # type: ignore[attr-defined]

        with pytest.raises(RuntimeError):
            store.set("TOKEN", "valor")
        assert store.delete("TOKEN") is False
        assert store.delete("nome inválido") is False

    def test_load_keyring_importa_ou_ignora_backend_incompativel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import dealhunter.runtime.secrets as secrets_module

        fake = SimpleNamespace(
            get_password=lambda *_args: None,
            set_password=lambda *_args: None,
            delete_password=lambda *_args: None,
        )
        monkeypatch.setattr(
            secrets_module, "importlib", SimpleNamespace(import_module=lambda _name: fake)
        )
        assert secrets_module.load_keyring() is fake

        incomplete = SimpleNamespace(get_password=lambda *_args: None)
        monkeypatch.setattr(
            secrets_module,
            "importlib",
            SimpleNamespace(import_module=lambda _name: incomplete),
        )
        assert secrets_module.load_keyring() is None

        def _raise(_name: str) -> None:
            raise RuntimeError("cofre quebrado")

        monkeypatch.setattr(secrets_module, "importlib", SimpleNamespace(import_module=_raise))
        assert secrets_module.load_keyring() is None

    def test_disable_env_ignora_backend(self) -> None:
        backend = FakeKeyring()
        backend.values[(KEYRING_SERVICE, "TOKEN")] = "do-keyring"
        store = SecretStore(environ={"DEALHUNTER_DISABLE_KEYRING": "1"}, backend=backend)

        assert store.keyring_available is False
        assert store.get("TOKEN") is None

    def test_adapters_e_notificador_consomem_keyring(self) -> None:
        backend = FakeKeyring()
        backend.values[(KEYRING_SERVICE, "DEALHUNTER_MELI_ACCESS_TOKEN")] = "token-meli"
        backend.values[(KEYRING_SERVICE, "DEALHUNTER_SMTP_PASSWORD")] = "senha-smtp"
        store = SecretStore(environ={}, backend=backend)

        adapters, _ = build_adapters(
            object(),  # type: ignore[arg-type]
            SourcesSettings(enabled=["mercadolivre"], respect_robots=False),
            secrets=store,
        )
        assert adapters[0]._token == "token-meli"  # type: ignore[attr-defined]

        notifier, warnings = build_notifier(
            NotificationSettings(
                smtp_host="smtp.example",
                email_from="remetente@example.com",
                email_to="destino@example.com",
            ),
            printer=lambda _text: None,
            secrets=store,
        )
        assert notifier.supports("email")
        assert warnings == []
        channel = notifier._channels["email"]  # type: ignore[attr-defined]
        assert channel._password == "senha-smtp"  # type: ignore[attr-defined]


class TestSecretsCli:
    def test_status_mostra_origem_sem_valor(
        self, tmp_path: Path, fake_keyring: FakeKeyring
    ) -> None:
        result = _invoke(
            tmp_path,
            ["--json", "secrets", "status"],
            env={"DEALHUNTER_SMTP_PASSWORD": "senha-que-nao-pode-vazar"},
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["keyring_available"] is True
        assert payload["command"] == "secrets.status"
        entry = next(
            item for item in payload["secrets"] if item["name"] == "DEALHUNTER_SMTP_PASSWORD"
        )
        assert entry["source"] == "env"
        assert "senha-que-nao-pode-vazar" not in result.output

    def test_set_e_delete_com_stdin_sem_ecoar(
        self, tmp_path: Path, fake_keyring: FakeKeyring
    ) -> None:
        set_result = _invoke(
            tmp_path,
            ["--json", "secrets", "set", "DEALHUNTER_SMTP_PASSWORD", "--stdin"],
            input="senha-super-secreta\n",
        )
        assert set_result.exit_code == 0, set_result.output
        assert "senha-super-secreta" not in set_result.output
        assert fake_keyring.values[(KEYRING_SERVICE, "DEALHUNTER_SMTP_PASSWORD")] == (
            "senha-super-secreta"
        )

        status = _invoke(tmp_path, ["--json", "secrets", "status"])
        entry = next(
            item
            for item in json.loads(status.output)["secrets"]
            if item["name"] == "DEALHUNTER_SMTP_PASSWORD"
        )
        assert entry["source"] == "keyring"

        deleted = _invoke(
            tmp_path,
            ["--json", "secrets", "delete", "DEALHUNTER_SMTP_PASSWORD", "--yes"],
        )
        assert deleted.exit_code == 0, deleted.output
        assert "DEALHUNTER_SMTP_PASSWORD" not in fake_keyring.values

    def test_set_interativo_nao_mostra_valor(
        self, tmp_path: Path, fake_keyring: FakeKeyring
    ) -> None:
        result = _invoke(
            tmp_path,
            ["secrets", "set", "DEALHUNTER_SMTP_PASSWORD"],
            input="outro-segredo\noutro-segredo\n",
        )
        assert result.exit_code == 0, result.output
        assert "outro-segredo" not in result.output
        assert fake_keyring.values[(KEYRING_SERVICE, "DEALHUNTER_SMTP_PASSWORD")] == (
            "outro-segredo"
        )

    def test_set_em_json_exige_stdin(self, tmp_path: Path, fake_keyring: FakeKeyring) -> None:
        result = _invoke(tmp_path, ["--json", "secrets", "set", "DEALHUNTER_SMTP_PASSWORD"])
        assert result.exit_code == 1
        assert fake_keyring.set_calls == 0

    def test_sem_keyring_falha_com_instrucao(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("dealhunter.runtime.secrets.load_keyring", lambda: None)
        monkeypatch.delenv("DEALHUNTER_DISABLE_KEYRING", raising=False)

        result = _invoke(
            tmp_path,
            ["secrets", "set", "DEALHUNTER_SMTP_PASSWORD", "--stdin"],
            input="segredo\n",
        )
        assert result.exit_code == 1
        assert "Keyring indisponível" in result.output
        assert "segredo" not in result.output.lower()

        deleted = _invoke(
            tmp_path,
            ["secrets", "delete", "DEALHUNTER_SMTP_PASSWORD", "--yes"],
        )
        assert deleted.exit_code == 1
        assert "Keyring indisponível" in deleted.output

    def test_nome_desconhecido_e_rejeitado(self, tmp_path: Path, fake_keyring: FakeKeyring) -> None:
        result = _invoke(
            tmp_path,
            ["secrets", "set", "QUALQUER_NOME", "--stdin"],
            input="segredo\n",
        )
        assert result.exit_code == 2
        assert fake_keyring.set_calls == 0
