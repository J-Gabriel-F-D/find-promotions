"""Formatação de dados de domínio para a janela (sem Tkinter)."""

from __future__ import annotations

from dealhunter.application.dto import HistoryReport, ReviewRow
from dealhunter.application.use_cases.reviews import ReviewReport
from dealhunter.domain.models import OfferView
from dealhunter.domain.value_objects.money import Money


def money(value: Money | None) -> str:
    return str(value) if value is not None else "n/d"


def when(value: str | None) -> str:
    if not value:
        return "n/d"
    return value.replace("T", " ")[:19]


def offer_detail(view: OfferView) -> str:
    """Texto factual da oferta selecionada; nada é inferido além dos dados."""
    offer = view.offer
    lines = [
        f"Produto: {view.product.title}",
        f"Loja: {view.store.name}" + (f" ({view.store.domain})" if view.store.domain else ""),
        "Vendedor: "
        + (
            f"{view.seller.name}"
            + (f" — nota {view.seller.rating:g}" if view.seller.rating else "")
            if view.seller is not None
            else "não informado pela fonte"
        ),
        f"Preço: {offer.price}"
        + (f" + frete {offer.shipping}" if offer.shipping is not None else " (frete não informado)")
        + f" = {offer.final_price}",
        f"Desconto: {view.discount.classification} — {view.discount.evidence}",
        f"Deal score: {view.deal_score:.1f}/100",
    ]

    if view.trust is None:
        lines.append("Confiança: não analisada (evidência insuficiente)")
    else:
        trust = view.trust
        lines.append(
            f"Confiança: {trust.score:.0f}/100 | cobertura {trust.analysis_confidence:.0%} | "
            f"risco {trust.risk_band}"
        )
        for signal in trust.signals[:8]:
            lines.append(f"  sinal {signal.code}: {signal.evidence}")
        for limitation in trust.limitations[:4]:
            lines.append(f"  limite: {limitation}")

    if view.reviews is not None:
        reviews = view.reviews
        lines.append(
            f"Avaliações: {reviews.rating_avg:.1f}/5 em {reviews.rating_count} "
            f"(negativas {reviews.negative_share:.1%})"
        )
    if view.best_coupon is not None:
        lines.append(f"Cupom declarado: {view.best_coupon.coupon.code}")
    if view.promotion is not None:
        lines.append(f"Promoção declarada: {view.promotion.kind} — {view.promotion.label}")
    if view.flags:
        lines.append("Alertas da análise: " + ", ".join(view.flags))
    lines.append(f"URL: {offer.url}")
    lines.append(
        f"Coletado em: {when(offer.collected_at.isoformat() if offer.collected_at else None)}"
    )
    return "\n".join(lines)


def history_text(report: HistoryReport) -> str:
    lines = [
        f"Produto: {report.product_title}",
        f"ID: {report.product_id}",
        f"Janela: {report.days} dia(s)",
    ]
    stats = report.stats
    if stats is None:
        lines.append("Estatísticas: histórico insuficiente")
    else:
        lines.extend(
            [
                f"Amostras: {stats.samples} em {stats.days_covered} dia(s)",
                f"Mínimo: {stats.minimum} | Máximo: {stats.maximum}",
                f"Média: {stats.average} | Mediana: {stats.median}",
                f"p10: {stats.p10} | p25: {stats.p25} | p75: {stats.p75} | p90: {stats.p90}",
                f"Atual: {stats.current} (posição {stats.position_pct:.0f}%)",
                "Histórico suficiente: " + ("sim" if stats.sufficient_history else "não"),
            ]
        )
    if report.warnings:
        lines.append("Avisos: " + " | ".join(report.warnings))
    return "\n".join(lines)


def _review_row(row: ReviewRow) -> str:
    review = row.review
    return (
        f"{row.store_name} ({review.source}): {review.rating_avg:.1f}/5 em "
        f"{review.rating_count} avaliações; negativas {review.negative_share:.1%}"
    )


def reviews_text(report: ReviewReport) -> str:
    lines = [f"Produto: {report.product_title}", f"ID: {report.product_id}", "", "Agregados:"]
    if not report.rows:
        lines.append("  nenhum agregado publicado pela fonte")
    for row in report.rows:
        lines.append("  " + _review_row(row))

    lines.append("")
    lines.append("Análise dos textos (determinística, derivada da nota declarada):")
    if not report.analyses:
        lines.append("  nenhum texto publicado pela fonte")
    for analysis_row in report.analyses:
        analysis = analysis_row.analysis
        lines.append(
            f"  {analysis_row.store_name} ({analysis_row.source}): "
            f"amostra {analysis.sample_size} (com texto {analysis.with_text}); "
            f"confiança {analysis.analysis_confidence:.2f}"
        )
        sentiment = ", ".join(
            f"{name} {count}" for name, count in sorted(analysis.sentiment_counts.items())
        )
        lines.append(f"    sentimento pela nota: {sentiment or 'n/d'}")
        complaints = ", ".join(f"{item.label} ({item.mentions})" for item in analysis.complaints)
        lines.append(f"    reclamações mencionadas: {complaints or 'nenhuma'}")
        for limitation in analysis.limitations:
            lines.append(f"    limite: {limitation}")
    if report.warnings:
        lines.append("Avisos: " + " | ".join(report.warnings))
    return "\n".join(lines)
