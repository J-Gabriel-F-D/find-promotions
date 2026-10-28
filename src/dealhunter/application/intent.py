"""Interpretação determinística de pedidos em linguagem natural.

Não usa IA. Cobre o vocabulario do dia a dia (preço, armazenamento, RAM, tela,
marca, categoria e condição) e e o *fallback* obrigatório quando a IA esta
desligada -- e a base de comparacao quando ela esta ligada.
"""

from __future__ import annotations

import re
from typing import Literal

from dealhunter.application.dto import QuerySpec
from dealhunter.domain.value_objects.money import Money
from dealhunter.services.text import (
    detect_brand,
    detect_category,
    normalize_text,
    parse_ram_gb,
    parse_screen_inches,
    parse_storage_gb,
)

_PRICE_WITH_CURRENCY = re.compile(r"r\$\s*([\d][\d.,]*)", re.IGNORECASE)
_PRICE_WITH_COMPARATOR = re.compile(
    r"(?:at[eé]|no\s*m[aá]ximo|m[aá]ximo|abaixo\s*de|menos\s*de|at[eé]\s*no\s*m[aá]ximo)"
    r"\s*(?:de\s*)?(?:r\$\s*)?([\d][\d.,]*)",
    re.IGNORECASE,
)
_SCREEN_CLAUSE = re.compile(
    r"(?:tela[^.;]{0,25}?(\d{1,2}[.,]\d))|(\d{1,2}[.,]\d)\s*(?:pol(?:egadas)?|\")",
    re.IGNORECASE,
)
_FILLER = re.compile(
    r"\b(quero|preciso|procuro|busco|um|uma|uns|umas|de|do|da|com|para|que|seja|tenha|"
    r"pelo|menos|no|maximo|ate|abaixo|acima|por|e|ou|comprar|compraria)\b",
    re.IGNORECASE,
)
# Palavras que não ajudam a busca no marketplace (ja viram filtro estruturado).
# Comparadas sempre contra texto normalizado (sem acento).
_SEARCH_STOPWORDS = {"ram", "ssd", "hd", "memoria", "armazenamento", "gb", "tb", "pol"}
_USED_TERMS = ("usado", "seminovo", "semi novo", "recondicionado")


def _strip_screen_clause(text: str) -> str:
    """Remove a clausula de tela para o numero (ex.: 6,5") não virar preço."""
    return _SCREEN_CLAUSE.sub(" ", text)


def extract_max_price(text: str) -> int | None:
    """Extrai o teto de preço; ignora numeros de tela e de capacidade."""
    cleaned = _strip_screen_clause(text)

    match = _PRICE_WITH_COMPARATOR.search(cleaned)
    if match:
        return _to_cents(match.group(1))

    amounts = _PRICE_WITH_CURRENCY.findall(cleaned)
    if len(amounts) == 1:
        return _to_cents(amounts[0])
    return None


def _to_cents(value: str) -> int | None:
    try:
        return Money.parse(value).cents
    except ValueError:
        return None


def _build_search_term(text: str, brand: str | None, category: str | None) -> str:
    """Texto de busca enxuto: sem preço, sem filler, com capacidades."""
    cleaned = _PRICE_WITH_CURRENCY.sub(" ", _PRICE_WITH_COMPARATOR.sub(" ", text))
    cleaned = _SCREEN_CLAUSE.sub(" ", cleaned)
    cleaned = re.sub(r"[\d.,]+\s*(gb|tb)\b", " ", cleaned, flags=re.IGNORECASE)
    words = [word for word in re.split(r"[^\w]+", cleaned) if word]
    words = [
        word
        for word in words
        if not _FILLER.fullmatch(normalize_text(word))
        and normalize_text(word) not in _SEARCH_STOPWORDS
    ]
    if not words and brand:
        words = [brand]
    if category and category not in {normalize_text(word) for word in words}:
        words.append(category)
    return " ".join(words[:8]).strip()


def parse_query(text: str, *, default_limit: int = 20) -> QuerySpec:
    """Converte uma frase livre em ``QuerySpec`` estruturado."""
    raw = " ".join(text.split())
    if not raw:
        raise ValueError("descreva o produto que voce procura")

    brand = detect_brand(raw)
    category = detect_category(raw)
    storage = parse_storage_gb(raw)
    ram = parse_ram_gb(raw)
    screen = parse_screen_inches(raw)
    max_price = extract_max_price(raw)
    condition: Literal["new", "used"] = (
        "used" if any(term in normalize_text(raw) for term in _USED_TERMS) else "new"
    )

    return QuerySpec(
        raw=raw,
        product=_build_search_term(raw, brand, category),
        brand=brand,
        category=category,
        storage_gb=storage,
        ram_gb=ram,
        screen_max_inches=screen,
        max_price_cents=max_price,
        condition=condition,
        limit=default_limit,
    )
