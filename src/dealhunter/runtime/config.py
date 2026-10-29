"""Configuração da aplicação.

Precedência (do mais forte para o mais fraco)::

    flags da CLI  >  variáveis DEALHUNTER_*  >  --config explícito
                  >  ./.dealhunter.toml (projeto)  >  config do usuário  >  defaults

Segredos (tokens, senhas) **não** moram no TOML: o arquivo guarda apenas o nome
da credencial no keyring ou da variavel de ambiente correspondente.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from dealhunter.runtime.paths import AppPaths

LogLevel = Literal["debug", "info", "warning", "error"]
ColorMode = Literal["auto", "always", "never"]

PROJECT_CONFIG_NAME = ".dealhunter.toml"
ENV_PREFIX = "DEALHUNTER_"


class ConfigError(RuntimeError):
    """Erro de configuração com mensagem amigavel para o usuário."""


# --------------------------------------------------------------------- secoes
class GeneralSettings(BaseModel):
    language: str = "pt-BR"
    currency: str = "BRL"
    timezone: str = "America/Sao_Paulo"
    results_limit: int = Field(default=20, ge=1, le=200)
    log_level: LogLevel = "info"
    color: ColorMode = "auto"
    unicode: bool = True


class SearchSettings(BaseModel):
    timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    max_concurrency: int = Field(default=6, ge=1, le=32)
    default_max_price_cents: int | None = Field(default=None, ge=0)
    cache_ttl_seconds: int = Field(default=300, ge=0)


class MonitorSettings(BaseModel):
    interval_seconds: int = Field(default=600, ge=60)
    quiet_hours_start: str = "22:00"
    quiet_hours_end: str = "07:00"
    cooldown_minutes: int = Field(default=720, ge=0)
    max_active_alerts: int = Field(default=50, ge=1, le=1_000)


class AISettings(BaseModel):
    enabled: bool = False
    model: str | None = None
    api_key_env: str = "DEALHUNTER_AI_API_KEY"
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    max_input_chars: int = Field(default=8000, ge=500, le=100_000)


class NotificationSettings(BaseModel):
    channels: list[str] = Field(default_factory=lambda: ["console"])
    email_from: str | None = None
    email_to: str | None = None
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: str | None = None
    smtp_password_env: str = "DEALHUNTER_SMTP_PASSWORD"
    use_starttls: bool = True
    whatsapp_template: str | None = None
    max_per_hour: int = Field(default=30, ge=1, le=1_000)


class SourcesSettings(BaseModel):
    enabled: list[str] = Field(default_factory=lambda: ["mercadolivre"])
    disabled: list[str] = Field(default_factory=list)
    feed_urls: list[str] = Field(default_factory=list)
    mercadolivre_token_env: str = "DEALHUNTER_MELI_ACCESS_TOKEN"
    user_agent: str = "DealHunter/0.1 (+https://github.com/dealhunter)"
    respect_robots: bool = True
    requests_per_minute: int = Field(default=30, ge=1, le=600)


class PrivacySettings(BaseModel):
    """Retenção local de dados pessoais (alertas e notificações)."""

    retention_days: int = Field(default=90, ge=1, le=3_650)


class AppConfig(BaseSettings):
    """Configuração efetiva, ja validada."""

    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_nested_delimiter="__",
        extra="ignore",
        validate_assignment=True,
    )

    general: GeneralSettings = Field(default_factory=GeneralSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    monitor: MonitorSettings = Field(default_factory=MonitorSettings)
    ai: AISettings = Field(default_factory=AISettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    sources: SourcesSettings = Field(default_factory=SourcesSettings)
    privacy: PrivacySettings = Field(default_factory=PrivacySettings)


@dataclass(frozen=True, slots=True)
class ConfigLoadResult:
    config: AppConfig
    files_read: tuple[Path, ...] = field(default_factory=tuple)


# --------------------------------------------------------------------- helpers
def _deep_merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in incoming.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"não foi possível ler {path}: {exc}") from exc

    try:
        # utf-8-sig: editores do Windows (Notepad, Set-Content) gravam BOM, que
        # o parser TOML rejeita como "Invalid statement at line 1".
        data = tomllib.loads(raw.decode("utf-8-sig"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"TOML invalido em {path}: {exc}") from exc

    if not isinstance(data, dict):  # pragma: no cover - tomllib sempre devolve dict
        raise ConfigError(f"conteudo inesperado em {path}")
    return data


def _format_validation_error(exc: ValidationError) -> str:
    lines = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "(raiz)"
        lines.append(f"  - {location}: {error['msg']}")
    return "configuração inválida:\n" + "\n".join(lines)


# --------------------------------------------------------------------- carga
def load_config(
    paths: AppPaths,
    *,
    explicit_path: Path | None = None,
    project_dir: Path | None = None,
    environ: dict[str, str] | None = None,
) -> ConfigLoadResult:
    """Carrega defaults -> arquivos TOML -> variáveis de ambiente -> validação."""
    environ = dict(os.environ if environ is None else environ)
    files_read: list[Path] = []
    data: dict[str, Any] = {}

    user_config = paths.config_file
    if explicit_path is not None:
        if not explicit_path.exists():
            raise ConfigError(f"arquivo de configuração não encontrado: {explicit_path}")
        candidates = [explicit_path]
    else:
        candidates = []
        if user_config.exists():
            candidates.append(user_config)
        if project_dir is not None:
            project_config = project_dir / PROJECT_CONFIG_NAME
            if project_config.exists():
                candidates.append(project_config)

    for candidate in candidates:
        data = _deep_merge(data, _read_toml(candidate))
        files_read.append(candidate)

    # Ordem explicita: defaults (do modelo) -> arquivos -> variáveis de ambiente.
    # Não usamos a leitura automatica de env do BaseSettings para manter o
    # comportamento determinístico e testavel com um mapping injetado.
    try:
        config = AppConfig.model_validate(data)
        config = _apply_env_overrides(config, environ)
    except ValidationError as exc:
        raise ConfigError(_format_validation_error(exc)) from exc

    return ConfigLoadResult(config=config, files_read=tuple(files_read))


def _apply_env_overrides(config: AppConfig, environ: dict[str, str]) -> AppConfig:
    """Aplica ``DEALHUNTER_*`` de um mapping arbitrario (usado em testes)."""
    import json

    data = config.model_dump()
    for key, raw in environ.items():
        if not key.startswith(ENV_PREFIX) or "__" not in key:
            continue
        section, _, option = key[len(ENV_PREFIX) :].partition("__")
        section_key = section.lower()
        option_key = option.lower()
        if section_key not in data or not isinstance(data[section_key], dict):
            continue
        if option_key not in data[section_key]:
            continue

        current = data[section_key][option_key]
        if isinstance(current, bool):
            value: Any = raw.strip().lower() in {"1", "true", "yes", "on"}
        elif isinstance(current, int) and not isinstance(current, bool):
            value = int(raw)
        elif isinstance(current, float):
            value = float(raw)
        elif isinstance(current, list):
            value = json.loads(raw) if raw.strip().startswith("[") else raw.split(",")
        elif current is None:
            value = raw
        else:
            value = raw
        data[section_key][option_key] = value

    return AppConfig.model_validate(data)


def _mask_account(value: str | None) -> str | None:
    """Mascara a parte local de um e-mail/usuário, preservando o domínio."""
    if not value:
        return value
    local, separator, domain = value.partition("@")
    if not local:
        return "***"
    masked = f"{local[0]}***"
    return f"{masked}{separator}{domain}" if separator else masked


def _mask_feed_url(value: str) -> str:
    """Remove credenciais, query e fragmento de URLs exibidas."""
    try:
        parts = urlsplit(value)
        port = f":{parts.port}" if parts.port is not None else ""
    except ValueError:
        return "***"
    host = parts.hostname or ""
    if not parts.scheme or not host:
        return "***"
    if ":" in host:
        host = f"[{host}]"
    query = "***" if parts.query else ""
    return urlunsplit((parts.scheme, f"{host}{port}", parts.path, query, ""))


def mask_config_pii(config: AppConfig) -> AppConfig:
    """Copia da configuração com PII e segredos de URL mascarados.

    Usada apenas para exibição (`config show`). Os valores reais continuam
    disponíveis internamente para montar os canais e coletar feeds.
    """
    notifications = config.notifications.model_copy(
        update={
            "email_from": _mask_account(config.notifications.email_from),
            "email_to": _mask_account(config.notifications.email_to),
            "smtp_user": _mask_account(config.notifications.smtp_user),
        }
    )
    sources = config.sources.model_copy(
        update={"feed_urls": [_mask_feed_url(url) for url in config.sources.feed_urls]}
    )
    return config.model_copy(update={"notifications": notifications, "sources": sources})


def dump_config_toml(config: AppConfig, *, mask_pii: bool = True) -> str:
    """Serializa a configuração efetiva (sem segredos) como TOML."""
    import tomli_w

    if mask_pii:
        config = mask_config_pii(config)

    def strip_none(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: strip_none(item) for key, item in value.items() if item is not None}
        if isinstance(value, list):
            return [strip_none(item) for item in value]
        return value

    return tomli_w.dumps(strip_none(config.model_dump(mode="json")))
