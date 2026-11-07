"""Lógica da interface gráfica, independente de Tkinter.

Concentra validação de entrada e chamadas aos mesmos casos de uso da CLI.
Assim a janela é apenas apresentação e os testes rodam sem display.
"""

from __future__ import annotations

import webbrowser
from typing import cast
from urllib.parse import urlsplit

import typer

from dealhunter.adapters.sources.registry import KNOWN_SOURCES
from dealhunter.adapters.storage.repository import SqliteRepository
from dealhunter.application.dto import (
    AlertRule,
    HistoryReport,
    QuerySpec,
    RiskBandName,
    SearchReport,
    StoredAlert,
)
from dealhunter.application.intent import parse_query
from dealhunter.application.use_cases.alerts import AlertOutcome, create_alert
from dealhunter.application.use_cases.monitor import MonitorRunResult
from dealhunter.application.use_cases.reviews import ReviewReport
from dealhunter.cli.parsing import parse_money_option, parse_percent_option
from dealhunter.cli.wiring import (
    ensure_database,
    run_alerts_check,
    run_history,
    run_monitor,
    run_reviews,
    run_search,
)
from dealhunter.gui.errors import GuiError
from dealhunter.runtime.container import RuntimeContext

SOURCE_OPTIONS = ("config", *KNOWN_SOURCES)
SORT_OPTIONS = ("best", "price", "reputation")
RISK_OPTIONS = ("", "low", "moderate", "elevated")


def _money(raw: str, field: str) -> int | None:
    try:
        return parse_money_option(raw, option=field)
    except typer.BadParameter as exc:
        raise GuiError(str(exc)) from exc


def _percent(raw: str, field: str) -> float | None:
    try:
        return parse_percent_option(raw, option=field)
    except typer.BadParameter as exc:
        raise GuiError(str(exc)) from exc


def _optional_float(raw: str, field: str, *, low: float, high: float) -> float | None:
    text = raw.strip().replace(",", ".")
    if not text:
        return None
    try:
        value = float(text)
    except ValueError as exc:
        raise GuiError(f"valor inválido para {field}: {raw!r}") from exc
    if not low <= value <= high:
        raise GuiError(f"{field} deve ficar entre {low:g} e {high:g}")
    return value


class GuiController:
    """Fachada síncrona usada pelos botões da janela."""

    def __init__(self, rt: RuntimeContext) -> None:
        self._rt = rt
        ensure_database(rt)
        self._repository = SqliteRepository(rt.database)

    @property
    def channels(self) -> tuple[str, ...]:
        return tuple(self._rt.config.notifications.channels)

    @property
    def config_path(self) -> str:
        return str(self._rt.config_path or self._rt.paths.config_file)

    def search(
        self,
        *,
        query: str,
        max_price: str = "",
        source: str = "config",
        limit: int = 20,
        sort: str = "best",
    ) -> SearchReport:
        if not query.strip():
            raise GuiError("informe uma busca")
        try:
            spec = parse_query(query, default_limit=limit)
        except ValueError as exc:
            raise GuiError(str(exc)) from exc

        updates: dict[str, object] = {"limit": limit, "sort": sort}
        if max_price.strip():
            updates["max_price_cents"] = _money(max_price, "preço máximo")
        try:
            spec = QuerySpec.model_validate({**spec.model_dump(), **updates})
        except ValueError as exc:
            raise GuiError(str(exc)) from exc

        sources = None if source == "config" else [source]
        try:
            return run_search(self._rt, spec, sources=sources)
        except Exception as exc:  # a janela precisa mostrar a falha, não sumir
            raise GuiError(f"falha na busca: {exc}") from exc

    def history(self, term: str, *, days: int | None = None) -> HistoryReport | None:
        if not term.strip():
            raise GuiError("informe um termo ou ID")
        try:
            return run_history(self._rt, term.strip(), days=days)
        except Exception as exc:
            raise GuiError(f"falha ao consultar histórico: {exc}") from exc

    def reviews(
        self, term: str, *, include_text: bool = False
    ) -> tuple[ReviewReport | None, list[str]]:
        if not term.strip():
            raise GuiError("informe um termo ou ID")
        try:
            return run_reviews(self._rt, term.strip(), include_text=include_text)
        except Exception as exc:
            raise GuiError(f"falha ao consultar avaliações: {exc}") from exc

    def list_alerts(self) -> list[StoredAlert]:
        return self._repository.list_alerts()

    def create_alert(
        self,
        *,
        query: str,
        max_price: str = "",
        discount: str = "",
        label: str = "",
        min_trust: str = "",
        max_risk: str = "",
        require_real_discount: bool = False,
        min_analysis_confidence: str = "",
    ) -> int:
        if not query.strip():
            raise GuiError("informe uma busca para o alerta")
        try:
            spec = parse_query(query)
        except ValueError as exc:
            raise GuiError(str(exc)) from exc

        max_price_cents = _money(max_price, "preço-alvo")
        min_discount = _percent(discount, "desconto")
        if max_price_cents is None and min_discount is None:
            raise GuiError("informe preço-alvo ou desconto mínimo")

        risk = max_risk.strip() or None
        if risk is not None and risk not in {"low", "moderate", "elevated"}:
            raise GuiError("risco máximo deve ser low, moderate ou elevated")
        try:
            rule = AlertRule(
                min_trust=_optional_float(min_trust, "confiança mínima", low=0, high=100),
                max_risk=cast(RiskBandName | None, risk),
                require_real_discount=require_real_discount,
                min_analysis_confidence=_optional_float(
                    min_analysis_confidence, "cobertura da análise", low=0, high=1
                ),
            )
            return create_alert(
                self._repository,
                query=query.strip(),
                spec=spec,
                max_price_cents=max_price_cents,
                min_discount_pct=min_discount,
                channels=list(self.channels),
                label=label.strip() or None,
                now=self._rt.clock.now(),
                max_active=self._rt.config.monitor.max_active_alerts,
                rule=rule,
            )
        except ValueError as exc:
            raise GuiError(str(exc)) from exc

    def set_alert_active(self, alert_id: int, *, active: bool) -> bool:
        return self._repository.set_alert_active(alert_id, active)

    def delete_alert(self, alert_id: int) -> bool:
        return self._repository.delete_alert(alert_id)

    def check_alerts(
        self, *, alert_id: int | None = None, source: str = "config"
    ) -> list[AlertOutcome]:
        sources = None if source == "config" else [source]
        try:
            return run_alerts_check(self._rt, alert_id=alert_id, sources=sources)
        except Exception as exc:
            raise GuiError(f"falha ao verificar alertas: {exc}") from exc

    def monitor_once(
        self, *, source: str = "config", ignore_quiet_hours: bool = False
    ) -> MonitorRunResult:
        sources = None if source == "config" else [source]
        try:
            return run_monitor(
                self._rt,
                once=True,
                sources=sources,
                ignore_quiet_hours=ignore_quiet_hours,
            )
        except Exception as exc:
            raise GuiError(f"falha ao executar o monitor: {exc}") from exc

    def last_monitor_run(self) -> dict[str, object] | None:
        return self._repository.last_monitor_run()

    def open_url(self, url: str) -> bool:
        """Abre apenas URLs http(s) publicadas pela fonte."""
        try:
            parts = urlsplit(url)
        except ValueError:
            return False
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return False
        return bool(webbrowser.open(url, new=2))
