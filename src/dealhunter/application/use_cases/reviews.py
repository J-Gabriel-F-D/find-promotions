"""Caso de uso: consultar o agregado de avaliações de um produto.

A Fase 2 exibe apenas o que a fonte publicou (nota, quantidade e distribuição).
Análise de sentimento/reclamações é Fase 3 e exige IA opcional com salvaguardas.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dealhunter.adapters.storage.repository import SqliteRepository
from dealhunter.application.dto import ReviewRow


@dataclass(frozen=True, slots=True)
class ReviewReport:
    product_id: str
    product_title: str
    rows: tuple[ReviewRow, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)


class ReviewService:
    def __init__(self, *, repository: SqliteRepository) -> None:
        self._repo = repository

    def build(self, term: str) -> tuple[ReviewReport | None, list[str]]:
        warnings: list[str] = []

        if term.startswith("off_"):
            resolved = self._repo.offer_product(term)
            if resolved is None:
                return None, [f"oferta não encontrada: {term}"]
        elif term.startswith("prd_"):
            title = self._repo.product_title(term)
            if title is None:
                return None, [f"produto não encontrado: {term}"]
            resolved = (term, title)
        else:
            matches = self._repo.find_products(term)
            if not matches:
                return None, [f"nenhum produto encontrado para: {term}"]
            if len(matches) > 1:
                warnings.append(
                    f"{len(matches)} produtos correspondem a '{term}'; usando o mais recente. "
                    "Use o ID para escolher outro."
                )
            resolved = (matches[0][0], matches[0][1])

        product_id, title = resolved
        rows = tuple(self._repo.reviews_for_product(product_id))
        return (
            ReviewReport(
                product_id=product_id,
                product_title=title,
                rows=rows,
                warnings=tuple(warnings),
            ),
            warnings,
        )
