"""Caso de uso: consultar avaliações agregadas e analisar textos individuais.

O agregado continua sendo apenas o que a fonte publicou (nota, quantidade e
distribuição). Textos individuais entram por feed JSON/fixture e são analisados
de forma determinística em :mod:`dealhunter.services.reviews`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dealhunter.adapters.storage.repository import SqliteRepository
from dealhunter.application.dto import ReviewRow
from dealhunter.services.reviews import ReviewTextAnalysis, analyze


@dataclass(frozen=True, slots=True)
class ReviewAnalysisRow:
    review_id: str
    store_name: str
    source: str
    analysis: ReviewTextAnalysis


@dataclass(frozen=True, slots=True)
class ReviewReport:
    product_id: str
    product_title: str
    rows: tuple[ReviewRow, ...]
    analyses: tuple[ReviewAnalysisRow, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)


class ReviewService:
    def __init__(self, *, repository: SqliteRepository) -> None:
        self._repo = repository

    def build(
        self,
        term: str,
        *,
        text_limit: int = 20,
        include_text: bool = False,
    ) -> tuple[ReviewReport | None, list[str]]:
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
        rows = tuple(self._repo.reviews_for_product(product_id, text_limit=max(1, text_limit)))
        analyses = tuple(
            ReviewAnalysisRow(
                review_id=row.review.id,
                store_name=row.store_name,
                source=row.review.source,
                analysis=analyze(row.review.texts, include_text=include_text),
            )
            for row in rows
        )
        if rows and not any(analysis.analysis.sample_size for analysis in analyses):
            warnings.append(
                "a fonte publicou apenas o agregado; nenhum texto individual foi "
                "coletado para este produto."
            )
        return (
            ReviewReport(
                product_id=product_id,
                product_title=title,
                rows=rows,
                analyses=analyses,
                warnings=tuple(warnings),
            ),
            warnings,
        )
