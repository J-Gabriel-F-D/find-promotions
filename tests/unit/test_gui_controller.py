"""Testes headless da lógica da interface gráfica (sem Tkinter/display).

A janela é só apresentação; aqui exercitamos o ``GuiController``, que chama os
mesmos casos de uso da CLI.
"""

from __future__ import annotations

import webbrowser

import pytest

import dealhunter.gui.controller as gui_controller
from dealhunter.gui.controller import GuiController
from dealhunter.gui.errors import GuiError
from dealhunter.gui.format import history_text, offer_detail, reviews_text
from dealhunter.runtime.container import RuntimeContext, build_runtime


@pytest.fixture()
def runtime(isolated_home, clock) -> RuntimeContext:
    """Runtime isolado em diretório temporário, com relógio congelado."""
    return build_runtime(clock=clock)


@pytest.fixture()
def controller(runtime: RuntimeContext) -> GuiController:
    return GuiController(runtime)


def test_search_fixture_returns_offers(controller: GuiController) -> None:
    report = controller.search(query="Redmi Note 14 256GB", source="fixture", limit=10)

    assert report.views, "a fonte fixture deve retornar ofertas"
    assert report.duration_ms >= 0
    assert all(view.offer.url.startswith("https://") for view in report.views)

    detail = offer_detail(report.views[0])
    assert "Produto:" in detail
    assert "Confiança:" in detail
    assert "https://" in detail


def test_search_rejects_empty_query(controller: GuiController) -> None:
    with pytest.raises(GuiError, match="informe uma busca"):
        controller.search(query="   ", source="fixture")


def test_search_rejects_invalid_price(controller: GuiController) -> None:
    with pytest.raises(GuiError, match="preço máximo"):
        controller.search(query="redmi", source="fixture", max_price="abc")


def test_search_rejects_invalid_sort(controller: GuiController) -> None:
    with pytest.raises(GuiError):
        controller.search(query="redmi", source="fixture", sort="inventado")


def test_history_after_search(controller: GuiController) -> None:
    controller.search(query="Redmi Note 14 256GB", source="fixture")

    report = controller.history("Redmi Note 14 256GB", days=90)

    assert report is not None
    assert report.product_title
    assert report.days == 90
    text = history_text(report)
    assert "Produto:" in text
    assert "Amostras:" in text or "histórico insuficiente" in text


def test_history_rejects_empty_term(controller: GuiController) -> None:
    with pytest.raises(GuiError, match="informe um termo"):
        controller.history("  ")


def test_reviews_after_search(controller: GuiController) -> None:
    controller.search(query="Redmi Note 14 256GB", source="fixture")

    report, warnings = controller.reviews("Redmi Note 14 256GB", include_text=True)

    assert report is not None
    assert report.rows
    assert not warnings
    text = reviews_text(report)
    assert "Agregados:" in text
    assert "Análise dos textos" in text


def test_reviews_rejects_empty_term(controller: GuiController) -> None:
    with pytest.raises(GuiError, match="informe um termo"):
        controller.reviews("  ")


def test_alert_create_list_pause_delete(controller: GuiController) -> None:
    alert_id = controller.create_alert(
        query="Redmi Note 14 256GB",
        max_price="2000",
        label="Redmi ate 2000",
    )

    alerts = controller.list_alerts()
    assert [alert.id for alert in alerts] == [alert_id]
    assert alerts[0].label == "Redmi ate 2000"

    assert controller.set_alert_active(alert_id, active=False) is True
    paused = controller.list_alerts()[0]
    assert paused.active is False

    assert controller.delete_alert(alert_id) is True
    assert controller.list_alerts() == []


def test_alert_requires_price_or_discount(controller: GuiController) -> None:
    with pytest.raises(GuiError, match="preço-alvo ou desconto"):
        controller.create_alert(query="redmi")


def test_alert_rejects_empty_query(controller: GuiController) -> None:
    with pytest.raises(GuiError, match="informe uma busca"):
        controller.create_alert(query="   ", max_price="2000")


def test_alert_rejects_invalid_risk(controller: GuiController) -> None:
    with pytest.raises(GuiError, match="risco máximo"):
        controller.create_alert(query="redmi", max_price="2000", max_risk="alto")


def test_alert_rejects_invalid_min_trust(controller: GuiController) -> None:
    with pytest.raises(GuiError, match="confiança mínima"):
        controller.create_alert(query="redmi", max_price="2000", min_trust="101")


def test_alert_accepts_full_rule(controller: GuiController) -> None:
    alert_id = controller.create_alert(
        query="Redmi Note 14 256GB",
        discount="10",
        label="Regra completa",
        min_trust="60",
        max_risk="moderate",
        require_real_discount=True,
        min_analysis_confidence="0.5",
    )

    stored = controller.list_alerts()[0]
    assert stored.id == alert_id
    assert stored.rule.min_trust == 60
    assert stored.rule.max_risk == "moderate"
    assert stored.rule.require_real_discount is True
    assert stored.rule.min_analysis_confidence == 0.5


def test_alert_check_matches_fixture(controller: GuiController) -> None:
    alert_id = controller.create_alert(query="Redmi Note 14 256GB", max_price="2000")

    outcomes = controller.check_alerts(alert_id=alert_id, source="fixture")

    assert [outcome.alert_id for outcome in outcomes] == [alert_id]
    assert outcomes[0].matched is True
    assert outcomes[0].price is not None
    assert outcomes[0].source_url


def test_monitor_once_records_run(controller: GuiController) -> None:
    result = controller.monitor_once(source="fixture")

    assert result.trigger == "once"
    assert len(result.cycles) == 1
    last = controller.last_monitor_run()
    assert last is not None
    assert last["id"] == result.run_id


def test_search_wraps_backend_failure(
    controller: GuiController, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("falha simulada")

    monkeypatch.setattr(gui_controller, "run_search", boom)

    with pytest.raises(GuiError, match="falha na busca"):
        controller.search(query="redmi", source="fixture")


def test_check_alerts_wraps_backend_failure(
    controller: GuiController, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("falha simulada")

    monkeypatch.setattr(gui_controller, "run_alerts_check", boom)

    with pytest.raises(GuiError, match="falha ao verificar alertas"):
        controller.check_alerts(source="fixture")


def test_monitor_once_wraps_backend_failure(
    controller: GuiController, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("falha simulada")

    monkeypatch.setattr(gui_controller, "run_monitor", boom)

    with pytest.raises(GuiError, match="falha ao executar o monitor"):
        controller.monitor_once(source="fixture")


def test_open_url_accepts_http_and_https(
    controller: GuiController, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[tuple[str, int]] = []

    def fake_open(url: str, *, new: int) -> bool:
        opened.append((url, new))
        return True

    monkeypatch.setattr(webbrowser, "open", fake_open)

    assert controller.open_url("https://demo.local/oferta") is True
    assert controller.open_url("http://demo.local/oferta") is True
    assert opened == [
        ("https://demo.local/oferta", 2),
        ("http://demo.local/oferta", 2),
    ]


@pytest.mark.parametrize(
    "url",
    [
        "",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "ftp://demo.local/x",
        "https://",
        "http://[::1",
    ],
)
def test_open_url_rejects_unsafe(
    controller: GuiController, monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    called: list[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda target, *, new: called.append(target))

    assert controller.open_url(url) is False
    assert called == []
