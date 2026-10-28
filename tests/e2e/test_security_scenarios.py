"""Cenários ponta a ponta exigidos, incluindo falha parcial e oferta suspeita."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from dealhunter.cli.app import app
from dealhunter.domain.models import CollectedOffer

runner = CliRunner()


class StaticAdapter:
    def __init__(
        self,
        *,
        source_id: str = "static",
        offers: list[CollectedOffer] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.id = source_id
        self.label = f"Fonte {source_id}"
        self.capabilities = frozenset({"search"})
        self._offers = offers or []
        self._error = error

    async def search(self, _spec: Any) -> list[CollectedOffer]:
        if self._error is not None:
            raise self._error
        return list(self._offers)


def _offer(**overrides: Any) -> CollectedOffer:
    values: dict[str, Any] = {
        "source_id": "static",
        "title": "Xiaomi Redmi Note 14 256GB 8GB RAM",
        "url": "https://loja.example/produto/1",
        "source_url": "https://loja.example/feed",
        "price_cents": 164_990,
        "store_name": "Loja Exemplo",
        "store_domain": "loja.example",
        "seller_name": "Vendedor Exemplo",
        "seller_rating": 4.8,
        "shipping_cents": 0,
        "brand": "Xiaomi",
        "collected_at": datetime(2026, 3, 15, 12, tzinfo=UTC),
    }
    values.update(overrides)
    return CollectedOffer(**values)


def _patch_adapters(monkeypatch: pytest.MonkeyPatch, adapters: list[StaticAdapter]) -> None:
    monkeypatch.setattr(
        "dealhunter.cli.wiring.build_adapters",
        lambda *_args, **_kwargs: (adapters, []),
    )


def _invoke(tmp_path: Path, args: list[str]):
    return runner.invoke(app, args, env={"DEALHUNTER_HOME": str(tmp_path / "home")})


class TestRequiredScenarios:
    def test_busca_normal(self, tmp_path: Path) -> None:
        result = _invoke(
            tmp_path,
            ["--json", "search", "Redmi Note 14 256GB", "--source", "fixture"],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["results"]
        assert payload["sources"][0]["status"] == "ok"

    def test_alerta_abaixo_do_alvo(self, tmp_path: Path) -> None:
        created = _invoke(tmp_path, ["alerts", "create", "redmi", "--max-price", "1700"])
        assert created.exit_code == 0, created.output

        checked = _invoke(tmp_path, ["--json", "alerts", "check", "--source", "fixture"])
        assert checked.exit_code == 0, checked.output
        outcome = json.loads(checked.output)["outcomes"][0]
        assert outcome["matched"] is True
        assert outcome["price_cents"] <= 170_000

    def test_oferta_suspeita_usa_historico_proprio(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        history = tuple((days, 10_000) for days in (1, 10, 20, 30, 40, 50, 60, 70, 80, 90))
        adapter = StaticAdapter(
            offers=[
                _offer(
                    price_cents=20_000,
                    list_price_cents=60_000,
                    history=history,
                )
            ]
        )
        _patch_adapters(monkeypatch, [adapter])

        result = _invoke(tmp_path, ["--json", "search", "redmi", "--source", "static"])
        assert result.exit_code == 0, result.output
        first = json.loads(result.output)["results"][0]
        assert first["discount"]["classification"] == "suspicious"
        assert "não corroborado" in first["discount"]["evidence"]

    def test_falha_de_fonte_com_resultado_parcial(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        good = StaticAdapter(source_id="boa", offers=[_offer()])
        bad = StaticAdapter(
            source_id="ruim",
            error=RuntimeError("token=segredo-123 usuario@example.com"),
        )
        _patch_adapters(monkeypatch, [good, bad])

        result = _invoke(tmp_path, ["--json", "search", "redmi", "--source", "static"])
        assert result.exit_code == 4, result.output
        payload = json.loads(result.output)
        assert len(payload["results"]) == 1
        statuses = {item["id"]: item for item in payload["sources"]}
        assert statuses["boa"]["status"] == "ok"
        assert statuses["ruim"]["status"] == "error"
        assert "segredo-123" not in json.dumps(payload)
        assert "usuario@example.com" not in json.dumps(payload)

    def test_todas_as_fontes_falham(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        bad = StaticAdapter(source_id="ruim", error=RuntimeError("fora do ar"))
        _patch_adapters(monkeypatch, [bad])

        result = _invoke(tmp_path, ["--json", "search", "redmi", "--source", "static"])
        assert result.exit_code == 5, result.output
        assert json.loads(result.output)["results"] == []

    def test_entrada_maliciosa_nao_derruba_a_cli(self, tmp_path: Path) -> None:
        payloads = [
            "\x1b[31m[red]{{7*7}}</red>\x00",
            "'; DROP TABLE product; --",
            "<script>alert(1)</script>",
            "../../etc/passwd",
        ]
        for payload in payloads:
            result = _invoke(
                tmp_path,
                ["--json", "search", payload, "--source", "fixture"],
            )
            assert result.exit_code in {0, 3}, result.output
            assert "\x1b[31m" not in result.output
            json.loads(result.output)


class TestTrustGuardrails:
    def test_nao_inventa_pontuacao_de_confianca_ou_fraude(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["--json", "search", "redmi", "--source", "fixture"])
        payload = json.loads(result.output)
        assert payload["picks"]["safest"] is None
        dumped = json.dumps(payload, ensure_ascii=False).lower()
        assert "trust_score" not in dumped
        assert "fraudulento" not in dumped
        assert "100% seguro" not in dumped

    def test_avaliacoes_nao_viram_garantia(self, tmp_path: Path) -> None:
        search = _invoke(
            tmp_path, ["--json", "search", "Redmi Note 14 256GB", "--source", "fixture"]
        )
        assert search.exit_code == 0, search.output
        result = _invoke(tmp_path, ["--json", "reviews", "Redmi Note 14 256GB"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload.get("sources") is not None
        assert "Não é análise de sentimento nem de reclamações" in payload["warnings"][0]
        assert "garantia" not in json.dumps(payload).lower()
