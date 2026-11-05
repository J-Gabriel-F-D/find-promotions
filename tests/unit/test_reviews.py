"""Testes da análise determinística de avaliações individuais."""

from __future__ import annotations

from datetime import UTC, datetime

from dealhunter.domain.models import ReviewText
from dealhunter.services.reviews import REVIEW_DISCLAIMER, analyze


def _text(
    rating: int,
    body: str,
    *,
    title: str = "",
    days_ago: int = 0,
    store_id: str = "str_a",
) -> ReviewText:
    return ReviewText(
        product_id="prd_a",
        store_id=store_id,
        source="fixture",
        source_url="https://demo.local/feed",
        rating=rating,
        body=body,
        title=title,
        reviewed_at=datetime(2026, 3, 1, 12, tzinfo=UTC).replace(day=max(1, 28 - days_ago)),
        collected_at=datetime(2026, 3, 15, 12, tzinfo=UTC),
        confidence=0.4,
    )


class TestSentimento:
    def test_deriva_da_nota_declarada(self) -> None:
        analysis = analyze(
            [
                _text(5, "Gostei."),
                _text(4, "Bom."),
                _text(3, "Ok."),
                _text(2, "Ruim."),
                _text(1, "Péssimo."),
            ]
        )
        assert analysis.sample_size == 5
        assert analysis.sentiment_counts == {"positive": 2, "neutral": 1, "negative": 2}
        assert analysis.sentiment_share == {
            "positive": 0.4,
            "neutral": 0.2,
            "negative": 0.4,
        }

    def test_amostra_vazia_nao_inventa_sentimento(self) -> None:
        analysis = analyze([])
        assert analysis.sample_size == 0
        assert analysis.analysis_confidence == 0.0
        assert analysis.complaints == ()
        assert "nenhum texto individual" in analysis.limitations[0]
        assert analysis.disclaimer == REVIEW_DISCLAIMER


class TestReclamacoes:
    def test_categoriza_mencoes_e_guarda_evidencia(self) -> None:
        analysis = analyze(
            [
                _text(1, "O produto chegou atrasado e o suporte não respondeu.", title="Atraso"),
                _text(2, "Veio diferente da descrição e pedi reembolso."),
                _text(5, "Entrega dentro do prazo, tudo certo."),
            ]
        )
        codes = {item.code for item in analysis.complaints}
        assert {"entrega", "atendimento", "produto_nao_conforme", "reembolso_devolucao"} <= codes

        entrega = next(item for item in analysis.complaints if item.code == "entrega")
        assert entrega.mentions == 1
        assert entrega.evidence[0].review_id.startswith("rvt_")
        assert entrega.evidence[0].rating == 1
        assert "atras" in entrega.evidence[0].matched_terms
        assert entrega.evidence[0].snippet is None

    def test_texto_positivo_nao_vira_reclamacao(self) -> None:
        analysis = analyze([_text(5, "Entrega dentro do prazo e produto perfeito.")])
        assert analysis.complaints == ()

    def test_frete_diferente_nao_e_produto_diferente(self) -> None:
        analysis = analyze([_text(1, "Cobraram frete diferente do combinado.")])
        codes = {item.code for item in analysis.complaints}
        assert "cobranca_frete" in codes
        assert "produto_nao_conforme" not in codes

    def test_snippet_so_aparece_com_opt_in(self) -> None:
        texts = [_text(1, "O produto quebrou e o atendimento não respondeu.")]
        hidden = analyze(texts)
        shown = analyze(texts, include_text=True)
        assert all(
            evidence.snippet is None
            for category in hidden.complaints
            for evidence in category.evidence
        )
        assert shown.complaints
        assert all(
            evidence.snippet for category in shown.complaints for evidence in category.evidence
        )

    def test_vocabulario_nao_acusa_fraude(self) -> None:
        analysis = analyze([_text(1, "Não chegou e o atendimento não respondeu.")])
        blob = f"{analysis.disclaimer} {' '.join(analysis.limitations)}".lower()
        assert "não confirma fraude" in blob
        assert "fraudulenta" not in blob
        assert "loja segura" not in blob


class TestConfiancaDaAnalise:
    def test_cresce_com_amostra_e_cobertura(self) -> None:
        one = analyze([_text(1, "Não chegou.")])
        many = analyze([_text(1, f"Não chegou; pedido {index}.") for index in range(20)])
        assert 0 < one.analysis_confidence < many.analysis_confidence <= 0.95
        assert one.analysis_confidence < 0.60

    def test_limita_amostra_pequena(self) -> None:
        analysis = analyze([_text(1, "Não chegou.")])
        assert any("amostra pequena" in item for item in analysis.limitations)

    def test_avaliacao_sem_corpo_conta_na_cobertura(self) -> None:
        analysis = analyze([_text(1, " "), _text(5, "Ok.")])
        assert analysis.with_text == 1
        assert any("sem texto" in item for item in analysis.limitations)
