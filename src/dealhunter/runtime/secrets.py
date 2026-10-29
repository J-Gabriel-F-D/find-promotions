"""Resolução de segredos: ambiente primeiro, keyring do sistema como fallback.

Valores nunca são gravados em TOML, logs, saídas JSON ou mensagens de erro.
O ``keyring`` é uma dependência opcional; quando ele não está instalado ou o
cofre do sistema não está disponível, o DealHunter continua operando apenas
com variáveis de ambiente.
"""

from __future__ import annotations

import importlib
import os
import re
from collections.abc import Mapping
from typing import Protocol

KEYRING_SERVICE = "dealhunter"
MAX_SECRET_CHARS = 4_096
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_DISABLE_ENV = "DEALHUNTER_DISABLE_KEYRING"


class KeyringBackend(Protocol):
    def get_password(self, service_name: str, username: str) -> str | None: ...

    def set_password(self, service_name: str, username: str, password: str) -> None: ...

    def delete_password(self, service_name: str, username: str) -> None: ...


def load_keyring() -> KeyringBackend | None:
    """Importa o keyring opcional sem transformá-lo em dependência obrigatória."""
    try:
        module = importlib.import_module("keyring")
    except Exception:
        return None
    if not all(
        hasattr(module, attribute)
        for attribute in ("get_password", "set_password", "delete_password")
    ):
        return None
    return module


def is_valid_secret_name(name: str) -> bool:
    return bool(_NAME.fullmatch(name))


def _truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


class SecretStore:
    """Consulta e administra segredos com precedência explícita do ambiente.

    O ``backend`` é injetável para testes; em produção ele é carregado sob
    demanda. Nenhuma exceção do cofre chega ao chamador, pois mensagens de
    backends podem conter detalhes internos.
    """

    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        backend: KeyringBackend | None = None,
    ) -> None:
        self._environ = dict(os.environ if environ is None else environ)
        self._backend = backend
        self._backend_loaded = backend is not None
        self._disable = _truthy(self._environ.get(_DISABLE_ENV))

    @property
    def keyring_available(self) -> bool:
        return self._get_backend() is not None

    def get(self, name: str) -> str | None:
        if not is_valid_secret_name(name):
            return None
        from_env = self._environ.get(name)
        if from_env:
            return from_env
        backend = self._get_backend()
        if backend is None:
            return None
        try:
            value = backend.get_password(KEYRING_SERVICE, name)
        except Exception:
            return None
        return value or None

    def source(self, name: str) -> str | None:
        """Diz de onde o valor vem, sem devolvê-lo."""
        if not is_valid_secret_name(name):
            return None
        if self._environ.get(name):
            return "env"
        return "keyring" if self.get(name) is not None else None

    def set(self, name: str, value: str) -> None:
        if not is_valid_secret_name(name):
            raise ValueError("nome de segredo inválido")
        if not value or len(value) > MAX_SECRET_CHARS or any(ord(char) < 32 for char in value):
            raise ValueError("valor de segredo inválido")
        backend = self._get_backend()
        if backend is None:
            raise RuntimeError("keyring indisponível")
        try:
            backend.set_password(KEYRING_SERVICE, name, value)
        except Exception as exc:
            raise RuntimeError("falha ao gravar no keyring") from exc

    def delete(self, name: str) -> bool:
        if not is_valid_secret_name(name):
            return False
        backend = self._get_backend()
        if backend is None:
            return False
        try:
            backend.delete_password(KEYRING_SERVICE, name)
        except Exception:
            return False
        return True

    def _get_backend(self) -> KeyringBackend | None:
        if self._disable:
            return None
        if not self._backend_loaded:
            self._backend = load_keyring()
            self._backend_loaded = True
        return self._backend
