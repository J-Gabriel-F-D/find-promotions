"""Análise determinística de avaliações individuais publicadas pela fonte.

A análise não inventa sentimento nem reclamação: o sentimento é derivado da
nota declarada e as categorias de reclamação são apenas menções explícitas no
texto, sempre rastreáveis até a avaliação de origem. Nenhum modelo de linguagem
é usado aqui; a IA continua opcional e desligada por padrão.

Vocabulário obrigatório: "menção", "sinal", "amostra". Nunca "fraude
confirmada", "loja insegura" ou generalização para toda a base de clientes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import log1p

from dealhunter.domain.models import ReviewText
from dealhunter.services.text import normalize_text

REVIEW_RULES_VERSION = "reviews-v1"
REVIEW_DISCLAIMER = (
    "Análise determinística dos textos publicados pela fonte. O sentimento é "
    "derivado da nota declarada e as reclamações são menções textuais; isso não "
    "confirma fraude nem representa toda a base de clientes."
)

# (código, rótulo, termos normalizados). Termos são radicais/pt-br sem acento.
_COMPLAINT_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "entrega",
        "Entrega/prazo",
        (
            "entrega",
            "atras",
            "correio",
            "transportadora",
            "prazo",
            "envio",
            "demorou",
            "nao chegou",
        ),
    ),
    (
        "produto_nao_conforme",
        "Produto diferente do anúncio",
        (
            "veio diferente",
            "produto diferente",
            "modelo diferente",
            "cor diferente",
            "diferente da descricao",
            "diferente do anuncio",
            "errado",
            "nao corresponde",
            "outro modelo",
            "falsific",
            "generico",
        ),
    ),
    (
        "defeito_qualidade",
        "Defeito/qualidade",
        (
            "defeito",
            "quebr",
            "ruim",
            "pessimo",
            "falha",
            "nao funciona",
            "parou de funcionar",
            "fragil",
        ),
    ),
    (
        "atendimento",
        "Atendimento/suporte",
        (
            "atendimento",
            "suporte",
            "sem resposta",
            "nao respondeu",
            "ignorou",
            "sac",
        ),
    ),
    (
        "reembolso_devolucao",
        "Reembolso/devolução",
        (
            "reembolso",
            "estorno",
            "devoluc",
            "cancel",
            "dinheiro de volta",
        ),
    ),
    (
        "cobranca_frete",
        "Cobrança/frete",
        (
            "cobranca",
            "cobrado",
            "taxa",
            "frete",
            "juros",
            "valor diferente",
        ),
    ),
    (
        "garantia",
        "Garantia/assistência",
        ("garantia", "assistencia", "conserto"),
    ),
    (
        "embalagem",
        "Embalagem",
        ("embalagem", "caixa", "amassad", "danificad"),
    ),
    (
        "estoque_anuncio",
        "Estoque/anúncio",
        ("sem estoque", "indisponivel", "anuncio", "cancelaram o pedido"),
    ),
)

_NEGATIVE_CUES = (
    "nao",
    "nunca",
    "ruim",
    "pessimo",
    "defeito",
    "atras",
    "demor",
    "problema",
    "erro",
    "quebr",
    "cancel",
    "reembolso",
    "estorno",
    "cobranc",
    "faltou",
    "diferente",
    "amassad",
)


@dataclass(frozen=True, slots=True)
class ComplaintEvidence:
    """Referência rastreável a uma linha que mencionou a categoria."""

    review_id: str
    rating: int
    matched_terms: tuple[str, ...]
    snippet: str | None = None


@dataclass(frozen=True, slots=True)
class ComplaintCategory:
    code: str
    label: str
    mentions: int
    evidence: tuple[ComplaintEvidence, ...]


@dataclass(frozen=True, slots=True)
class ReviewTextAnalysis:
    sample_size: int
    with_text: int
    sentiment_counts: dict[str, int]
    sentiment_share: dict[str, float]
    complaints: tuple[ComplaintCategory, ...]
    analysis_confidence: float
    limitations: tuple[str, ...]
    rules_version: str = REVIEW_RULES_VERSION
    disclaimer: str = REVIEW_DISCLAIMER


def _sentiment(rating: int) -> str:
    if rating >= 4:
        return "positive"
    if rating <= 2:
        return "negative"
    return "neutral"


def _snippet(text: str, *, limit: int = 160) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _matched_terms(text: str, terms: tuple[str, ...]) -> tuple[str, ...]:
    normalized = normalize_text(text)
    return tuple(term for term in terms if term in normalized)


def _has_negative_cue(text: str) -> bool:
    normalized = normalize_text(text)
    return any(cue in normalized for cue in _NEGATIVE_CUES)


def _confidence(sample_size: int, with_text: int) -> float:
    if sample_size <= 0:
        return 0.0
    coverage = with_text / sample_size
    size_factor = min(1.0, log1p(sample_size) / log1p(30))
    return round(min(0.95, 0.10 + 0.55 * size_factor + 0.20 * coverage), 2)


def analyze(texts: Sequence[ReviewText], *, include_text: bool = False) -> ReviewTextAnalysis:
    """Classifica os textos sem afirmar fraude e sem inventar conteúdo."""
    sample = tuple(texts)
    with_text = sum(1 for text in sample if text.body.strip())
    counts = {"positive": 0, "neutral": 0, "negative": 0}
    for text in sample:
        counts[_sentiment(text.rating)] += 1

    total = len(sample)
    shares = {name: round(count / total, 3) if total else 0.0 for name, count in counts.items()}

    evidence: dict[str, list[ComplaintEvidence]] = {}
    for text in sample:
        if not text.body.strip():
            continue
        if text.rating > 3 and not _has_negative_cue(f"{text.title} {text.body}"):
            continue
        for code, _label, terms in _COMPLAINT_RULES:
            matched = _matched_terms(f"{text.title} {text.body}", terms)
            if not matched:
                continue
            bucket = evidence.setdefault(code, [])
            if len(bucket) >= 5:
                continue
            bucket.append(
                ComplaintEvidence(
                    review_id=text.id,
                    rating=text.rating,
                    matched_terms=matched,
                    snippet=_snippet(text.body) if include_text else None,
                )
            )

    labels = {code: label for code, label, _terms in _COMPLAINT_RULES}
    complaints = tuple(
        ComplaintCategory(
            code=code,
            label=labels[code],
            mentions=len(items),
            evidence=tuple(items),
        )
        for code, items in evidence.items()
    )
    complaints = tuple(sorted(complaints, key=lambda item: (-item.mentions, item.code)))

    limitations: list[str] = []
    if total == 0:
        limitations.append("nenhum texto individual publicado pela fonte")
    elif total < 3:
        limitations.append("amostra pequena de textos; não representa toda a base")
    if total and with_text < total:
        limitations.append("parte das avaliações veio sem texto")
    limitations.append("sentimento derivado da nota declarada, não de modelo de linguagem")
    limitations.append("reclamações são menções no texto, não confirmação de fraude")

    return ReviewTextAnalysis(
        sample_size=total,
        with_text=with_text,
        sentiment_counts=counts,
        sentiment_share=shares,
        complaints=complaints,
        analysis_confidence=_confidence(total, with_text),
        limitations=tuple(limitations),
    )
