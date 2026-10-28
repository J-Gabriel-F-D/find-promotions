"""Filtros de compatibilidade entre a busca do usuário e a oferta coletada.

Regra: um atributo **desconhecido** não elimina a oferta (seria pior esconder
uma possível boa compra), mas um atributo **conhecido e divergente** elimina.
Todo descarte tem um motivo contabilizado -- isso alimenta a observabilidade.
"""

from __future__ import annotations

from dealhunter.application.dto import QuerySpec
from dealhunter.domain.models import CollectedOffer
from dealhunter.services.text import (
    detect_brand,
    normalize_text,
    parse_ram_gb,
    parse_storage_gb,
)

REASONS: dict[str, str] = {
    "acima_do_preco_maximo": "acima do preço máximo",
    "abaixo_do_preco_minimo": "abaixo do preço mínimo",
    "armazenamento_diferente": "armazenamento diferente",
    "ram_insuficiente": "RAM abaixo do exigido",
    "marca_diferente": "marca diferente",
    "condicao_diferente": "condição diferente",
    "loja_bloqueada": "loja bloqueada",
    "frete_acima_do_limite": "frete acima do limite",
    "sem_estoque": "sem estoque",
}


def evaluate(spec: QuerySpec, offer: CollectedOffer) -> str | None:
    """Devolve o motivo do descarte ou ``None`` se a oferta e elegivel."""
    if offer.availability == "out_of_stock":
        return "sem_estoque"

    if spec.max_price_cents is not None and offer.price_cents > spec.max_price_cents:
        return "acima_do_preco_maximo"
    if spec.min_price_cents is not None and offer.price_cents < spec.min_price_cents:
        return "abaixo_do_preco_minimo"

    if spec.condition != "any" and offer.condition != spec.condition:
        return "condicao_diferente"

    if spec.storage_gb is not None:
        storage = _spec_int(offer.specs.get("armazenamento")) or parse_storage_gb(offer.title)
        if storage is not None and storage != spec.storage_gb:
            return "armazenamento_diferente"

    if spec.ram_gb is not None:
        ram = _spec_int(offer.specs.get("memoria_ram")) or parse_ram_gb(offer.title)
        if ram is not None and ram > 0 and ram < spec.ram_gb:
            return "ram_insuficiente"

    if spec.brand is not None:
        brand = offer.brand or detect_brand(offer.title)
        if brand is not None and brand != spec.brand:
            return "marca_diferente"

    if spec.exclude_stores:
        blocked = {normalize_text(name) for name in spec.exclude_stores}
        candidates = {normalize_text(offer.store_name), normalize_text(offer.store_domain or "")}
        if blocked & {candidate for candidate in candidates if candidate}:
            return "loja_bloqueada"

    if (
        spec.max_shipping_cents is not None
        and offer.shipping_cents is not None
        and offer.shipping_cents > spec.max_shipping_cents
    ):
        return "frete_acima_do_limite"

    return None


def _spec_int(raw: str | None) -> int | None:
    if not raw:
        return None
    digits = "".join(char for char in raw if char.isdigit())
    return int(digits) if digits else None
