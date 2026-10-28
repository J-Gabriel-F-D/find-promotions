"""Testes do objeto de valor Money (dinheiro em centavos)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from dealhunter.domain.value_objects.money import Money


class TestParsing:
    @pytest.mark.parametrize(
        ("text", "expected_cents"),
        [
            ("R$ 1.649,00", 164_900),
            ("1.649,00", 164_900),
            ("1,649.00", 164_900),
            ("1649", 164_900),
            ("1.649", 164_900),
            ("1,649", 164_900),
            ("1649.5", 164_950),
            ("R$ 0,99", 99),
            ("15,90", 1_590),
            ("-R$ 50,00", -5_000),
        ],
    )
    def test_parse_aceita_formatos_comuns(self, text: str, expected_cents: int) -> None:
        assert Money.parse(text).cents == expected_cents

    @pytest.mark.parametrize("text", ["", "   ", "abc", "R$"])
    def test_parse_rejeita_texto_invalido(self, text: str) -> None:
        with pytest.raises(ValueError):
            Money.parse(text)


class TestConstruction:
    def test_from_decimal_arredonda_meio_para_cima(self) -> None:
        assert Money.from_decimal(Decimal("10.005")).cents == 1_001

    def test_rejeita_float(self) -> None:
        with pytest.raises(TypeError):
            Money.from_decimal(10.5)  # type: ignore[arg-type]

    def test_rejeita_moeda_invalida(self) -> None:
        with pytest.raises(ValueError):
            Money(100, "REAL")

    def test_normaliza_moeda_para_maiuscula(self) -> None:
        assert Money(100, "brl").currency == "BRL"


class TestFormatting:
    def test_formata_padrao_brasileiro(self) -> None:
        assert Money(164_900).format() == "R$ 1.649,00"
        assert Money(99).format() == "R$ 0,99"
        assert Money(-5_000).format() == "-R$ 50,00"

    def test_formata_sem_simbolo(self) -> None:
        assert Money(164_900).format(symbol=False) == "1.649,00"

    def test_roundtrip_parse_format(self) -> None:
        original = Money(123_456)
        assert Money.parse(original.format()) == original


class TestArithmetic:
    def test_soma_e_subtracao(self) -> None:
        assert Money(1_000) + Money(500) == Money(1_500)
        assert Money(1_000) - Money(1_500) == Money(-500)

    def test_moeda_incompativel_falha(self) -> None:
        with pytest.raises(ValueError):
            _ = Money(100, "BRL") + Money(100, "USD")

    def test_multiplicacao_por_inteiro(self) -> None:
        assert Money(1_000) * 3 == Money(3_000)

    def test_comparacoes(self) -> None:
        assert Money(100) < Money(200)
        assert Money(200) >= Money(200)

    def test_percentage_below(self) -> None:
        assert Money(1_649).percentage_below(Money(1_999)) == Decimal("17.5")
        assert Money(2_100).percentage_below(Money(2_000)) < 0
