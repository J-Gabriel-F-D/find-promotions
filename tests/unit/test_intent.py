"""Testes do parser deterministico de linguagem natural."""

from __future__ import annotations

import pytest

from dealhunter.application.intent import parse_query


class TestPrice:
    @pytest.mark.parametrize(
        ("text", "cents"),
        [
            ("Redmi Note 256GB até R$1800", 180_000),
            ("até R$ 2.000", 200_000),
            ("no máximo 1.500", 150_000),
            ("abaixo de 3500 reais", 350_000),
            ("quero um celular por R$ 1.899,90", 189_990),
            ("Redmi Note 256GB", None),
        ],
    )
    def test_extrai_teto_de_preco(self, text: str, cents: int | None) -> None:
        assert parse_query(text).max_price_cents == cents

    def test_nao_confunde_tela_com_preco(self) -> None:
        spec = parse_query('Quero um celular com até R$ 2.000, tela de no máximo 6,5", 8 GB de RAM')
        assert spec.max_price_cents == 200_000
        assert spec.screen_max_inches == 6.5


class TestSpecs:
    def test_celular_completo(self) -> None:
        spec = parse_query(
            'Quero um celular com até R$ 2.000, tela de no máximo 6,5", '
            "8 GB de RAM, 256 GB de armazenamento, boa bateria e que seja resistente."
        )
        assert spec.category == "smartphone"
        assert spec.max_price_cents == 200_000
        assert spec.screen_max_inches == 6.5
        assert spec.ram_gb == 8
        assert spec.storage_gb == 256

    def test_notebook_completo(self) -> None:
        spec = parse_query(
            "Quero um notebook para programação, até R$ 4.000, com pelo menos 16 GB de RAM, "
            "SSD de 512 GB e processador Ryzen 5 ou Intel i5."
        )
        assert spec.category == "notebook"
        assert spec.max_price_cents == 400_000
        assert spec.ram_gb == 16
        assert spec.storage_gb == 512

    def test_marca_e_categoria(self) -> None:
        spec = parse_query("Redmi Note 256GB até R$1800")
        assert spec.brand == "xiaomi"
        assert spec.storage_gb == 256
        assert "redmi" in spec.search_terms.lower()

    def test_produto_nao_contem_preco(self) -> None:
        spec = parse_query("notebook para programação até R$4000")
        assert "4000" not in spec.search_terms
        assert "r" not in spec.search_terms.split()

    def test_condicao_usado(self) -> None:
        assert parse_query("iPhone 13 usado até 2500").condition == "used"

    def test_texto_vazio_falha(self) -> None:
        with pytest.raises(ValueError):
            parse_query("   ")

    def test_search_terms_respeita_produto_explicito(self) -> None:
        from dealhunter.application.dto import QuerySpec

        spec = QuerySpec(product="galaxy s24", max_price_cents=300_000)
        assert spec.search_terms == "galaxy s24"
