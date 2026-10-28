"""Testes dos filtros de compatibilidade entre busca e oferta."""

from __future__ import annotations

import pytest

from dealhunter.application.dto import QuerySpec
from dealhunter.domain.models import CollectedOffer
from dealhunter.services.matching import evaluate


def _offer(**overrides: object) -> CollectedOffer:
    base: dict[str, object] = {
        "source_id": "fixture",
        "title": "Xiaomi Redmi Note 14 256GB 8GB RAM",
        "url": "https://loja.example/p",
        "source_url": "https://loja.example/p",
        "price_cents": 150_000,
        "shipping_cents": 0,
        "store_name": "Loja Teste",
        "store_domain": "loja.example",
        "brand": "xiaomi",
    }
    base.update(overrides)
    return CollectedOffer(**base)  # type: ignore[arg-type]


class TestFiltros:
    def test_oferta_compativel_passa(self) -> None:
        spec = QuerySpec(product="redmi", max_price_cents=200_000, storage_gb=256)
        assert evaluate(spec, _offer()) is None

    def test_preco_acima_do_teto(self) -> None:
        spec = QuerySpec(product="redmi", max_price_cents=100_000)
        assert evaluate(spec, _offer()) == "acima_do_preco_maximo"

    def test_preco_abaixo_do_minimo(self) -> None:
        spec = QuerySpec(product="redmi", min_price_cents=200_000)
        assert evaluate(spec, _offer()) == "abaixo_do_preco_minimo"

    def test_armazenamento_divergente(self) -> None:
        spec = QuerySpec(product="redmi", storage_gb=512)
        assert evaluate(spec, _offer()) == "armazenamento_diferente"

    def test_ram_insuficiente(self) -> None:
        spec = QuerySpec(product="redmi", ram_gb=16)
        assert evaluate(spec, _offer()) == "ram_insuficiente"

    def test_ram_desconhecida_nao_elimina(self) -> None:
        spec = QuerySpec(product="produto", ram_gb=16)
        offer = _offer(title="Produto generico", brand=None, specs={})
        assert evaluate(spec, offer) is None

    def test_marca_divergente(self) -> None:
        spec = QuerySpec(product="celular", brand="samsung")
        assert evaluate(spec, _offer()) == "marca_diferente"

    def test_condicao_divergente(self) -> None:
        spec = QuerySpec(product="redmi", condition="new")
        assert evaluate(spec, _offer(condition="used")) == "condicao_diferente"

    def test_condicao_any_aceita_tudo(self) -> None:
        spec = QuerySpec(product="redmi", condition="any")
        assert evaluate(spec, _offer(condition="used")) is None

    @pytest.mark.parametrize("blocked", ["Loja Teste", "loja.example"])
    def test_loja_bloqueada(self, blocked: str) -> None:
        spec = QuerySpec(product="redmi", exclude_stores=[blocked])
        assert evaluate(spec, _offer()) == "loja_bloqueada"

    def test_frete_acima_do_limite(self) -> None:
        spec = QuerySpec(product="redmi", max_shipping_cents=1_000)
        assert evaluate(spec, _offer(shipping_cents=2_000)) == "frete_acima_do_limite"

    def test_frete_desconhecido_nao_elimina(self) -> None:
        spec = QuerySpec(product="redmi", max_shipping_cents=1_000)
        assert evaluate(spec, _offer(shipping_cents=None)) is None

    def test_sem_estoque(self) -> None:
        spec = QuerySpec(product="redmi")
        assert evaluate(spec, _offer(availability="out_of_stock")) == "sem_estoque"
