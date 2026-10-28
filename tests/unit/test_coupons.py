"""Testes da avaliação local de cupons."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from dealhunter.domain.models import Coupon
from dealhunter.domain.value_objects.money import Money
from dealhunter.services import coupons

NOW = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)


def make_coupon(**overrides: object) -> Coupon:
    data: dict[str, object] = {
        "store_id": "str_loja",
        "code": "X10",
        "kind": "percent",
        "value": 10,
        "source": "fixture",
        "source_url": "https://demo.local/ofertas",
        "collected_at": NOW,
    }
    data.update(overrides)
    return Coupon(**data)  # type: ignore[arg-type]


def evaluate(coupon: Coupon, *, price_cents: int = 100_000, shipping_cents: int | None = 0):
    shipping = Money(shipping_cents) if shipping_cents is not None else None
    return coupons.evaluate(coupon, price=Money(price_cents), shipping=shipping, now=NOW)


class TestEvaluate:
    def test_percentual_aplica_sobre_o_produto(self) -> None:
        result = evaluate(make_coupon(value=10))
        assert result.applicable
        assert result.discount == Money(10_000)
        assert result.final_price == Money(90_000)
        assert result.estimate is True

    def test_percentual_respeita_teto_de_desconto(self) -> None:
        result = evaluate(make_coupon(value=50, max_discount=Money(15_000)))
        assert result.applicable
        assert result.discount == Money(15_000)
        assert result.final_price == Money(85_000)

    def test_valor_fixo_nao_ultrapassa_o_preco(self) -> None:
        result = evaluate(make_coupon(kind="fixed", value=500_000), price_cents=100_000)
        assert result.applicable
        assert result.discount == Money(100_000)
        assert result.final_price == Money(0)

    def test_frete_gratis_desconta_somente_o_frete(self) -> None:
        result = evaluate(
            make_coupon(kind="free_shipping", value=0),
            price_cents=100_000,
            shipping_cents=2_500,
        )
        assert result.applicable
        assert result.discount == Money(2_500)
        assert result.final_price == Money(100_000)

    def test_frete_desconhecido_nao_e_estimado(self) -> None:
        result = evaluate(make_coupon(kind="free_shipping", value=0), shipping_cents=None)
        assert not result.applicable
        assert "frete não informado" in result.reason

    def test_frete_ja_gratis_nao_gera_beneficio(self) -> None:
        result = evaluate(make_coupon(kind="free_shipping", value=0), shipping_cents=0)
        assert not result.applicable
        assert "já é grátis" in result.reason

    def test_minimo_de_compra_bloqueia(self) -> None:
        result = evaluate(make_coupon(min_purchase=Money(150_000)), price_cents=100_000)
        assert not result.applicable
        assert "valor mínimo" in result.reason
        assert result.discount == Money(0)

    def test_cupom_expirado_nao_aplica(self) -> None:
        result = evaluate(make_coupon(valid_until=NOW - timedelta(minutes=1)))
        assert not result.applicable
        assert "expirado" in result.reason

    def test_cupom_agendado_nao_aplica(self) -> None:
        result = evaluate(make_coupon(valid_from=NOW + timedelta(hours=1)))
        assert not result.applicable
        assert "a partir de" in result.reason

    def test_cupom_vigente_aplica(self) -> None:
        result = evaluate(
            make_coupon(valid_from=NOW - timedelta(hours=1), valid_until=NOW + timedelta(hours=1))
        )
        assert result.applicable
        assert result.coupon.state_at(NOW) == "active"

    def test_percentual_invalido_nao_aplica(self) -> None:
        result = evaluate(make_coupon(value=150))
        assert not result.applicable
        assert "inválido" in result.reason

    def test_cupom_sem_janela_e_estado_desconhecido(self) -> None:
        coupon = make_coupon()
        assert coupon.state_at(NOW) == "unknown"
        assert evaluate(coupon).applicable

    def test_cupom_nunca_e_marcado_como_validado_pela_fonte(self) -> None:
        assert make_coupon().validation == "unverified"


class TestBest:
    def test_escolhe_maior_desconto_aplicavel(self) -> None:
        price = Money(100_000)
        evaluations = coupons.evaluate_all(
            [
                make_coupon(code="A", value=5),
                make_coupon(code="B", value=20),
                make_coupon(code="C", value=90, min_purchase=Money(500_000)),
            ],
            price=price,
            shipping=Money(0),
            now=NOW,
        )
        best = coupons.best_evaluation(evaluations)
        assert best is not None
        assert best.coupon.code == "B"
        assert best.discount == Money(20_000)

    def test_sem_cupom_aplicavel_retorna_none(self) -> None:
        evaluations = coupons.evaluate_all(
            [make_coupon(valid_until=NOW - timedelta(days=1))],
            price=Money(100_000),
            shipping=Money(0),
            now=NOW,
        )
        assert coupons.best_evaluation(evaluations) is None


def test_describe_benefit() -> None:
    assert coupons.describe_benefit(make_coupon(value=10)) == "10% de desconto"
    assert (
        coupons.describe_benefit(make_coupon(kind="fixed", value=5_000)) == "R$ 50,00 de desconto"
    )
    assert coupons.describe_benefit(make_coupon(kind="free_shipping", value=0)) == "frete grátis"
