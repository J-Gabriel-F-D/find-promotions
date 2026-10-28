"""Montagem dos servicos para os comandos (composition root da CLI)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace

from dealhunter.adapters.http.client import HttpClient
from dealhunter.adapters.notify.base import Notifier
from dealhunter.adapters.notify.registry import build_notifier
from dealhunter.adapters.sources.base import CollectorRunner
from dealhunter.adapters.sources.registry import build_adapters
from dealhunter.adapters.storage.repository import SqliteRepository
from dealhunter.application.dto import HistoryReport, QuerySpec, SearchReport
from dealhunter.application.use_cases.alerts import AlertOutcome, AlertService
from dealhunter.application.use_cases.search import HistoryService, SearchService
from dealhunter.runtime.container import RuntimeContext


@dataclass(frozen=True, slots=True)
class Stack:
    search: SearchService
    repository: SqliteRepository
    notifier: Notifier
    warnings: list[str]


def ensure_database(rt: RuntimeContext) -> None:
    """Cria o schema no primeiro uso (idempotente)."""
    rt.paths.ensure_directories()
    if rt.database.schema_version() is None:
        rt.database.migrate()


@asynccontextmanager
async def open_stack(
    rt: RuntimeContext, *, sources: list[str] | None = None
) -> AsyncIterator[Stack]:
    ensure_database(rt)
    settings = rt.config.sources
    if sources:
        settings = settings.model_copy(update={"enabled": list(sources)})

    http = HttpClient(
        user_agent=settings.user_agent,
        timeout=rt.config.search.timeout_seconds,
    )
    try:
        adapters, warnings = build_adapters(http, settings)
        if not adapters:
            warnings.append("nenhuma fonte habilitada: a busca não tem de onde coletar")

        runner = CollectorRunner(
            adapters,
            timeout=rt.config.search.timeout_seconds,
            max_concurrency=rt.config.search.max_concurrency,
        )
        repository = SqliteRepository(rt.database)
        notifier, notifier_warnings = build_notifier(
            rt.config.notifications,
            # Em modo `--json` o stdout precisa ficar limpo: o canal de console
            # e redundante, pois o resultado ja vai no envelope.
            printer=(lambda _text: None) if rt.json_output else rt.error_console.print,
        )
        yield Stack(
            search=SearchService(repository=repository, runner=runner, clock=rt.clock),
            repository=repository,
            notifier=notifier,
            warnings=warnings + notifier_warnings,
        )
    finally:
        await http.aclose()


def run_search(
    rt: RuntimeContext, spec: QuerySpec, *, sources: list[str] | None = None
) -> SearchReport:
    """Executa a busca em um event loop proprio (a CLI e sincrona)."""

    async def _run() -> SearchReport:
        async with open_stack(rt, sources=sources) as stack:
            report = await stack.search.search(spec)
            return replace(report, warnings=tuple(report.warnings) + tuple(stack.warnings))

    import asyncio

    return asyncio.run(_run())


def run_history(rt: RuntimeContext, term: str, *, days: int | None = None) -> HistoryReport | None:
    ensure_database(rt)
    service = HistoryService(repository=SqliteRepository(rt.database), clock=rt.clock)
    report, _warnings = service.build(term, days=days)
    return report


def run_alerts_check(
    rt: RuntimeContext, *, alert_id: int | None = None, sources: list[str] | None = None
) -> list[AlertOutcome]:
    async def _run() -> list[AlertOutcome]:
        async with open_stack(rt, sources=sources) as stack:
            service = AlertService(
                repository=stack.repository,
                search=stack.search,
                notifier=stack.notifier,
                clock=rt.clock,
            )
            return await service.check(alert_id)

    import asyncio

    return asyncio.run(_run())
