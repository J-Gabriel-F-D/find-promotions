"""Registro de fontes: monta os adapters habilitados na configuração.

Adicionar uma loja nova = criar um modulo que implemente ``SourceAdapter`` e
registrar aqui. Nenhum outro ponto do sistema precisa mudar.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from dealhunter.adapters.http.client import HttpClient
from dealhunter.adapters.http.robots import RobotsGuard
from dealhunter.adapters.sources.base import SourceAdapter
from dealhunter.adapters.sources.feed import FeedAdapter
from dealhunter.adapters.sources.fixture import FixtureAdapter
from dealhunter.adapters.sources.mercadolivre import MercadoLivreAdapter
from dealhunter.runtime.config import SourcesSettings

KNOWN_SOURCES = ("mercadolivre", "feed", "fixture")


def build_adapters(
    http: HttpClient,
    settings: SourcesSettings,
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[list[SourceAdapter], list[str]]:
    """Devolve ``(adapters, avisos)`` para os IDs habilitados."""
    environ = os.environ if environ is None else environ
    adapters: list[SourceAdapter] = []
    warnings: list[str] = []
    robots = RobotsGuard(http, user_agent=settings.user_agent) if settings.respect_robots else None

    for source_id in settings.enabled:
        if source_id in settings.disabled:
            warnings.append(f"fonte '{source_id}' esta desabilitada e foi ignorada")
            continue

        if source_id == "mercadolivre":
            token = environ.get(settings.mercadolivre_token_env) or None
            adapters.append(MercadoLivreAdapter(http, access_token=token))
        elif source_id == "fixture":
            adapters.append(FixtureAdapter())
        elif source_id == "feed":
            if not settings.feed_urls:
                warnings.append("fonte 'feed' habilitada sem 'feed_urls' configuradas")
                continue
            adapters.append(FeedAdapter(http, settings.feed_urls, robots=robots))
        else:
            warnings.append(
                f"fonte desconhecida: '{source_id}' (conhecidas: {', '.join(KNOWN_SOURCES)})"
            )

    return adapters, warnings
