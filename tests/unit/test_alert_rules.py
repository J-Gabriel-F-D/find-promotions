"""Testes das regras inteligentes de alerta (confiança, risco e desconto)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from dealhunter.adapters.storage.database import Database
from dealhunter.adapters.storage.repository import SqliteRepository
from dealhunter.application.dto import AlertRule, QuerySpec, StoredAlert
from dealhunter.application.use_cases.alerts import _matches, build_message, create_alert
from dealhunter.cli.app import app
from dealhunter.domain.models import (
    TRUST_DISCLAIMER,
    DiscountAssessment,
    OfferView,
    TrustAssessment,
)

runner = CliRunner()


def _view(make_offer_record, **overrides: object) -> OfferView:
    record = make_offer_record(price_cents=150_000)
    values: dict[str, object] = {
        "offer": record.offer,
        "product": record.product,
        "store": record.store,
        "seller": record.seller,
        "stats": None,
        "discount": DiscountAssessment("likely_real", "histórico sustenta o desconto"),
        "deal_score": 70.0,
        "trust": TrustAssessment(
            score=72.0,
            analysis_confidence=0.8,
            risk_band="moderate",
        ),
    }
    values.update(overrides)
    return OfferView(**values)  # type: ignore[arg-type]


def _alert(rule: AlertRule) -> StoredAlert:
    return StoredAlert(
        id=1,
        label="redmi",
        query="redmi",
        spec_json="{}",
        max_price_cents=200_000,
        min_discount_pct=None,
        channels=("console",),
        active=True,
        created_at="2026-03-15T12:00:00+00:00",
        last_checked_at=None,
        rule=rule,
    )


class TestAlertRule:
    def test_regra_vazia_preserva_comportamento(self, make_offer_record) -> None:
        matched, reason = _matches(_alert(AlertRule()), _view(make_offer_record))
        assert matched is True
        assert "meta" in reason

    def test_confianca_minima_rejeita_abaixo_do_limite(self, make_offer_record) -> None:
        matched, _ = _matches(_alert(AlertRule(min_trust=80.0)), _view(make_offer_record))
        assert matched is False

    def test_confianca_minima_aceita_acima_do_limite(self, make_offer_record) -> None:
        matched, reason = _matches(_alert(AlertRule(min_trust=70.0)), _view(make_offer_record))
        assert matched is True
        assert "confiança" in reason

    def test_risco_maximo_moderate_aceita_moderate(self, make_offer_record) -> None:
        matched, _ = _matches(_alert(AlertRule(max_risk="moderate")), _view(make_offer_record))
        assert matched is True

    def test_risco_maximo_low_rejeita_moderate(self, make_offer_record) -> None:
        matched, _ = _matches(_alert(AlertRule(max_risk="low")), _view(make_offer_record))
        assert matched is False

    def test_risco_sem_dados_nao_e_tratado_como_baixo(self, make_offer_record) -> None:
        trust = TrustAssessment(score=50.0, analysis_confidence=0.1, risk_band="insufficient_data")
        matched, _ = _matches(
            _alert(AlertRule(max_risk="elevated")),
            _view(make_offer_record, trust=trust),
        )
        assert matched is False

    def test_exige_desconto_corroborado(self, make_offer_record) -> None:
        suspicious = DiscountAssessment("suspicious", "anúncio sem lastro")
        matched, _ = _matches(
            _alert(AlertRule(require_real_discount=True)),
            _view(make_offer_record, discount=suspicious),
        )
        assert matched is False

    def test_cobertura_minima_da_analise(self, make_offer_record) -> None:
        trust = TrustAssessment(score=80.0, analysis_confidence=0.2, risk_band="low")
        matched, _ = _matches(
            _alert(AlertRule(min_analysis_confidence=0.5)),
            _view(make_offer_record, trust=trust),
        )
        assert matched is False

    def test_sem_trust_rejeita_regra_inteligente(self, make_offer_record) -> None:
        matched, _ = _matches(
            _alert(AlertRule(min_trust=1.0)),
            _view(make_offer_record, trust=None),
        )
        assert matched is False

    def test_mensagem_explica_confianca_e_nao_afirma_seguranca(self, make_offer_record) -> None:
        message = build_message(
            _alert(AlertRule()),
            _view(make_offer_record),
            "preço final atingiu a meta",
        )
        assert "Confiabilidade (probabilística): 72/100" in message.body
        assert "risco: moderate" in message.body
        assert TRUST_DISCLAIMER in message.body
        assert "Fase 3" not in message.body


class TestRulePersistence:
    def test_cria_e_le_regra(self, database: Database, clock) -> None:
        repo = SqliteRepository(database)
        alert_id = create_alert(
            repo,
            query="redmi",
            spec=QuerySpec(product="redmi"),
            max_price_cents=200_000,
            min_discount_pct=None,
            channels=["console"],
            label="redmi",
            now=clock.now(),
            rule=AlertRule(
                min_trust=60.0,
                max_risk="moderate",
                require_real_discount=True,
                min_analysis_confidence=0.3,
            ),
        )

        alert = repo.get_alert(alert_id)
        assert alert is not None
        assert alert.rule.min_trust == 60.0
        assert alert.rule.max_risk == "moderate"
        assert alert.rule.require_real_discount is True
        assert alert.rule.min_analysis_confidence == 0.3

    def test_remover_alerta_remove_regra_em_cascata(self, database: Database, clock) -> None:
        repo = SqliteRepository(database)
        alert_id = repo.create_alert(
            label="redmi",
            query="redmi",
            spec_json="{}",
            max_price_cents=200_000,
            min_discount_pct=None,
            channels=["console"],
            now=clock.now(),
            rule=AlertRule(min_trust=50.0),
        )
        repo.delete_alert(alert_id)
        with database.connect() as connection:
            remaining = connection.execute("SELECT COUNT(*) FROM alert_rule").fetchone()[0]
        assert remaining == 0


class TestRuleCli:
    def _invoke(self, tmp_path: Path, args: list[str]):
        return runner.invoke(app, args, env={"DEALHUNTER_HOME": str(tmp_path / "home")})

    def test_cria_alerta_com_filtros_e_lista(self, tmp_path: Path) -> None:
        created = self._invoke(
            tmp_path,
            [
                "--json",
                "alerts",
                "create",
                "redmi",
                "--max-price",
                "2000",
                "--min-trust",
                "60",
                "--max-risk",
                "moderate",
                "--require-real-discount",
                "--min-analysis-confidence",
                "0.3",
            ],
        )
        assert created.exit_code == 0, created.output
        payload = json.loads(created.output)
        assert payload["smart_rule"]

        listed = self._invoke(tmp_path, ["--json", "alerts", "list"])
        alert = json.loads(listed.output)["alerts"][0]
        assert alert["smart_rule"]
        assert "confiança" in alert["rule"]

    def test_risco_invalido_e_erro_de_uso(self, tmp_path: Path) -> None:
        result = self._invoke(
            tmp_path,
            ["alerts", "create", "redmi", "--max-price", "2000", "--max-risk", "alto"],
        )
        assert result.exit_code == 2
        assert "risco" in result.output.lower()

    def test_confianca_fora_da_escala_e_erro_de_uso(self, tmp_path: Path) -> None:
        result = self._invoke(
            tmp_path,
            ["alerts", "create", "redmi", "--max-price", "2000", "--min-trust", "150"],
        )
        assert result.exit_code == 2
