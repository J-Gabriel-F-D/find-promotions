"""Objeto de valor monetario.

Decisoes de projeto
-------------------
* Dinheiro e sempre armazenado em **centavos inteiros**. Ponto flutuante nao e
  usado em nenhum ponto do calculo de precos (evita 0.1 + 0.2 != 0.3).
* ``Decimal`` aparece apenas na conversao de/para texto, com arredondamento
  explicito ``ROUND_HALF_UP`` (o mesmo usado no varejo brasileiro).
* A moeda faz parte do valor: somar BRL com USD levanta erro em vez de produzir
  um numero silenciosamente errado.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_CENT = Decimal("0.01")
_SYMBOLS = {"BRL": "R$", "USD": "$", "EUR": "€"}
_SEPARATORS = re.compile(r"[^0-9,.\-]")


@dataclass(frozen=True, slots=True)
class Money:
    """Valor monetario imutavel, expresso em centavos."""

    cents: int
    currency: str = "BRL"

    def __post_init__(self) -> None:
        if isinstance(self.cents, bool) or not isinstance(self.cents, int):
            raise TypeError(f"cents deve ser int, recebido {type(self.cents).__name__}")
        code = (self.currency or "").strip().upper()
        if len(code) != 3 or not code.isalpha():
            raise ValueError(f"moeda invalida: {self.currency!r} (use ISO 4217, ex.: BRL)")
        object.__setattr__(self, "currency", code)

    # ------------------------------------------------------------------ criacao
    @classmethod
    def zero(cls, currency: str = "BRL") -> Money:
        return cls(0, currency)

    @classmethod
    def from_decimal(cls, value: Decimal | int | str, currency: str = "BRL") -> Money:
        """Converte um valor decimal em centavos, arredondando meio para cima."""
        if isinstance(value, float):  # pragma: no cover - guarda defensiva
            raise TypeError("use Decimal/str/int; float perde precisao")
        try:
            amount = Decimal(value)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"valor monetario invalido: {value!r}") from exc
        if not amount.is_finite():
            raise ValueError(f"valor monetario invalido: {value!r}")
        return cls(int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)), currency)

    @classmethod
    def parse(cls, text: str, currency: str = "BRL") -> Money:
        """Interpreta textos como ``R$ 1.649,00``, ``1,649.00`` ou ``1649``.

        Regras de desambiguacao (padrao pt-BR):
        * com '.' e ',' juntos, o ultimo separador e o decimal;
        * com apenas um separador repetido ou 3 digitos apos ele, e milhar;
        * demais casos, e decimal.
        """
        if not isinstance(text, str) or not text.strip():
            raise ValueError("texto monetario vazio")

        cleaned = _SEPARATORS.sub("", text.strip())
        negative = cleaned.startswith("-")
        cleaned = cleaned.lstrip("-").replace("-", "")
        if not cleaned or not any(ch.isdigit() for ch in cleaned):
            raise ValueError(f"texto monetario invalido: {text!r}")

        has_dot = "." in cleaned
        has_comma = "," in cleaned
        if has_dot and has_comma:
            decimal_sep = "." if cleaned.rfind(".") > cleaned.rfind(",") else ","
            thousands_sep = "," if decimal_sep == "." else "."
            cleaned = cleaned.replace(thousands_sep, "").replace(decimal_sep, ".")
        elif has_comma:
            parts = cleaned.split(",")
            cleaned = (
                cleaned.replace(",", "")
                if len(parts) > 2 or len(parts[-1]) == 3
                else cleaned.replace(",", ".")
            )
        elif has_dot:
            parts = cleaned.split(".")
            if len(parts) == 2 and len(parts[-1]) == 3:
                cleaned = cleaned.replace(".", "")

        money = cls.from_decimal(cleaned, currency)
        return cls(-money.cents, money.currency) if negative else money

    # ------------------------------------------------------------------ conversao
    def to_decimal(self) -> Decimal:
        return Decimal(self.cents) / 100

    def __str__(self) -> str:
        return self.format()

    def format(self, *, symbol: bool = True) -> str:
        """Formata no padrao pt-BR: ``R$ 1.649,00``."""
        sign = "-" if self.cents < 0 else ""
        absolute = abs(self.cents)
        units, centavos = divmod(absolute, 100)
        grouped = f"{units:,}".replace(",", ".")
        body = f"{grouped},{centavos:02d}"
        if not symbol:
            return f"{sign}{body}"
        return f"{sign}{_SYMBOLS.get(self.currency, self.currency)} {body}"

    # ------------------------------------------------------------------ aritmetica
    def _check(self, other: Money) -> None:
        if not isinstance(other, Money):
            raise TypeError(f"esperado Money, recebido {type(other).__name__}")
        if other.currency != self.currency:
            raise ValueError(f"moedas incompativeis: {self.currency} e {other.currency}")

    def __add__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.cents + other.cents, self.currency)

    def __sub__(self, other: Money) -> Money:
        self._check(other)
        return Money(self.cents - other.cents, self.currency)

    def __mul__(self, factor: int) -> Money:
        if isinstance(factor, bool) or not isinstance(factor, int):
            raise TypeError("multiplicador deve ser int (quantidade de parcelas/itens)")
        return Money(self.cents * factor, self.currency)

    __rmul__ = __mul__

    def __neg__(self) -> Money:
        return Money(-self.cents, self.currency)

    def __abs__(self) -> Money:
        return Money(abs(self.cents), self.currency)

    # ------------------------------------------------------------------ comparacao
    def _compare(self, other: object) -> int:
        if not isinstance(other, Money):
            return NotImplemented  # type: ignore[return-value]
        self._check(other)
        return (self.cents > other.cents) - (self.cents < other.cents)

    def __lt__(self, other: object) -> bool:
        return self._compare(other) < 0

    def __le__(self, other: object) -> bool:
        return self._compare(other) <= 0

    def __gt__(self, other: object) -> bool:
        return self._compare(other) > 0

    def __ge__(self, other: object) -> bool:
        return self._compare(other) >= 0

    __hash__ = object.__hash__

    # ------------------------------------------------------------------ utilidades
    def is_zero(self) -> bool:
        return self.cents == 0

    def is_positive(self) -> bool:
        return self.cents > 0

    def percentage_below(self, reference: Money) -> Decimal:
        """Percentual que este valor esta abaixo de ``reference``.

        Retorna negativo quando este valor e maior que a referencia.
        """
        self._check(reference)
        if reference.cents <= 0:
            raise ValueError("referencia deve ser maior que zero")
        delta = (reference.cents - self.cents) / reference.cents
        return (Decimal(delta) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
