"""Motor de preço: estatísticas historicas e detecção de falso desconto.

Regra central: o "preço anterior" informado pela loja **nunca** e tratado como
verdade. A comparacao e feita contra o histórico coletado pela propria
ferramenta; sem amostra suficiente, a resposta e "sem evidencia suficiente".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import ceil, floor

from dealhunter.domain.models import DiscountAssessment, PriceStats
from dealhunter.domain.value_objects.money import Money

MIN_SAMPLES = 8
MIN_DAYS = 45
# Tolerancia para considerar um "de" anunciado como fora do histórico.
CLAIM_TOLERANCE = 0.10


@dataclass(frozen=True, slots=True)
class Sample:
    collected_at: datetime
    price_cents: int


def _percentile(sorted_values: list[int], pct: float) -> int:
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * pct / 100
    lower, upper = floor(position), ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return round(sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction)


def compute_stats(
    samples: list[Sample],
    *,
    current_cents: int,
    currency: str = "BRL",
    min_samples: int = MIN_SAMPLES,
    min_days: int = MIN_DAYS,
) -> PriceStats | None:
    """Estatísticas descritivas; ``None`` quando não ha nenhuma amostra."""
    values = sorted(sample.price_cents for sample in samples)
    if not values:
        return None

    moments = sorted(sample.collected_at for sample in samples)
    days_covered = max((moments[-1] - moments[0]).days, 0)
    below_or_equal = sum(1 for value in values if value <= current_cents)

    return PriceStats(
        samples=len(values),
        days_covered=days_covered,
        minimum=Money(values[0], currency),
        maximum=Money(values[-1], currency),
        average=Money(round(sum(values) / len(values)), currency),
        median=Money(_percentile(values, 50), currency),
        p10=Money(_percentile(values, 10), currency),
        p25=Money(_percentile(values, 25), currency),
        p75=Money(_percentile(values, 75), currency),
        p90=Money(_percentile(values, 90), currency),
        current=Money(current_cents, currency),
        position_pct=round(below_or_equal / len(values) * 100, 1),
        sufficient_history=len(values) >= min_samples and days_covered >= min_days,
    )


def assess_discount(
    *,
    current: Money,
    list_price: Money | None,
    stats: PriceStats | None,
) -> DiscountAssessment:
    """Classifica o desconto em probabilidade, com a evidencia que a sustenta.

    Duas perguntas diferentes são respondidas em sequencia:

    1. o preço anterior anunciado e plausivel? (comparado ao histórico proprio)
    2. o preço atual esta baixo? (posição na série)

    Se o "de" não tem respaldo histórico, o desconto anunciado e classificado
    como suspeito mesmo que o preço atual seja bom -- são coisas distintas, e a
    interface mostra as duas.
    """
    if stats is None or not stats.sufficient_history:
        samples = stats.samples if stats else 0
        days = stats.days_covered if stats else 0
        sample_label = "amostra" if samples == 1 else "amostras"
        day_label = "dia" if days == 1 else "dias"
        return DiscountAssessment(
            classification="insufficient_evidence",
            evidence=(
                f"histórico insuficiente ({samples} {sample_label} em {days} {day_label}; "
                f"mínimo {MIN_SAMPLES} amostras e {MIN_DAYS} dias)"
            ),
        )

    claimed = list_price if list_price else None
    if claimed is not None and claimed.cents > stats.p90.cents * (1 + CLAIM_TOLERANCE):
        excess = round((claimed.cents / stats.p90.cents - 1) * 100)
        return DiscountAssessment(
            classification="suspicious",
            evidence=(
                f"desconto anunciado não corroborado: 'de' {claimed} está {excess}% "
                f"acima do p90 histórico ({stats.p90})"
            ),
        )

    if current.cents <= stats.p10.cents:
        return DiscountAssessment(
            classification="likely_real",
            evidence=(
                f"preço atual no p10 histórico ({stats.p10}); mínimo observado {stats.minimum}"
            ),
        )

    if current.cents <= stats.p75.cents:
        return DiscountAssessment(
            classification="normal",
            evidence=(
                f"dentro da faixa habitual (p25 {stats.p25} a p75 {stats.p75}); "
                f"média {stats.average}"
            ),
        )

    return DiscountAssessment(
        classification="normal",
        evidence=f"acima do p75 histórico ({stats.p75}); não há desconto relevante",
    )
