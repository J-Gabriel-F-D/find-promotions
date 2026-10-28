"""Testes do motor de preco (estatisticas e desconto)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from dealhunter.domain.value_objects.money import Money
from dealhunter.services.pricing import CLAIM_TOLERANCE, Sample, assess_discount, compute_stats

BASE = datetime(2026, 3, 1, tzinfo=UTC)


def _samples(prices: list[int], *, step_days: int = 10) -> list[Sample]:
    return [
        Sample(
            collected_at=BASE - timedelta(days=(len(prices) - index) * step_days), price_cents=price
        )
        for index, price in enumerate(prices)
    ]


class TestStats:
    def test_sem_amostras_retorna_none(self) -> None:
        assert compute_stats([], current_cents=100) is None

    def test_estatisticas_basicas(self) -> None:
        stats = compute_stats(_samples([100, 200, 300, 400]), current_cents=300)
        assert stats is not None
        assert stats.minimum == Money(100)
        assert stats.maximum == Money(400)
        assert stats.average == Money(250)
        assert stats.median == Money(250)
        assert stats.current == Money(300)
        assert stats.position_pct == 75.0

    def test_ordem_dos_percentis(self) -> None:
        stats = compute_stats(_samples(list(range(100, 1100, 100))), current_cents=500)
        assert stats is not None
        assert stats.p10 <= stats.p25 <= stats.median <= stats.p75 <= stats.p90

    def test_historico_suficiente_exige_amostras_e_dias(self) -> None:
        poucas = compute_stats(_samples([100] * 5, step_days=10), current_cents=100)
        assert poucas is not None and not poucas.sufficient_history

        recentes = compute_stats(_samples([100] * 9, step_days=1), current_cents=100)
        assert recentes is not None and not recentes.sufficient_history

        completas = compute_stats(_samples([100] * 9, step_days=10), current_cents=100)
        assert completas is not None and completas.sufficient_history

    def test_uma_amostra_nao_quebra_percentil(self) -> None:
        stats = compute_stats(_samples([500]), current_cents=500)
        assert stats is not None
        assert stats.median == Money(500)


class TestDiscount:
    def _history(self) -> object:
        stats = compute_stats(
            _samples([180_000, 190_000, 200_000, 210_000, 220_000] * 2), current_cents=180_000
        )
        assert stats is not None
        return stats

    def test_sem_historico_e_evidencia_insuficiente(self) -> None:
        result = assess_discount(current=Money(100), list_price=None, stats=None)
        assert result.classification == "insufficient_evidence"

    def test_historico_curto_e_evidencia_insuficiente(self) -> None:
        stats = compute_stats(_samples([100, 200]), current_cents=100)
        result = assess_discount(current=Money(100), list_price=None, stats=stats)
        assert result.classification == "insufficient_evidence"
        assert "histórico insuficiente" in result.evidence

    def test_preco_no_piso_historico_e_provavelmente_real(self) -> None:
        result = assess_discount(current=Money(100), list_price=None, stats=self._history())
        assert result.classification == "likely_real"

    def test_preco_na_faixa_usual_e_normal(self) -> None:
        result = assess_discount(current=Money(205_000), list_price=None, stats=self._history())
        assert result.classification == "normal"

    def test_de_inflado_e_suspeito(self) -> None:
        stats = self._history()
        assert stats.p90.cents > 0
        inflated = Money(round(stats.p90.cents * (1 + CLAIM_TOLERANCE) * 1.2))
        result = assess_discount(current=Money(180_000), list_price=inflated, stats=stats)
        assert result.classification == "suspicious"
        assert "não corroborado" in result.evidence

    def test_de_plausivel_nao_marca_suspeito(self) -> None:
        stats = self._history()
        plausible = Money(round(stats.p90.cents * 1.02))
        result = assess_discount(current=Money(180_000), list_price=plausible, stats=stats)
        assert result.classification != "suspicious"

    @pytest.mark.parametrize("price", [150_000, 260_000])
    def test_classificacao_sempre_no_vocabulario_permitido(self, price: int) -> None:
        result = assess_discount(current=Money(price), list_price=None, stats=self._history())
        assert result.classification in {
            "likely_real",
            "normal",
            "suspicious",
            "insufficient_evidence",
        }
