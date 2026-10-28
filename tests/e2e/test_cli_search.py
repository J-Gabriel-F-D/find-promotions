"""Testes ponta a ponta dos comandos search/history."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from dealhunter.cli.app import app

runner = CliRunner()


def _invoke(tmp_path: Path, args: list[str]):
    return runner.invoke(app, args, env={"DEALHUNTER_HOME": str(tmp_path / "home")})


class TestSearch:
    def test_busca_com_fixture_retorna_ofertas(self, tmp_path: Path) -> None:
        result = _invoke(
            tmp_path,
            ["--json", "search", "Redmi Note 14 256GB", "--source", "fixture"],
        )
        assert result.exit_code == 0, result.output

        payload = json.loads(result.output)
        assert payload["schema_version"] == "1.0"
        assert payload["command"] == "search"
        assert payload["results"]
        assert payload["stats"]["collected"] >= 1

        first = payload["results"][0]
        for field in ("offer_id", "product_id", "title", "price_cents", "url", "source"):
            assert field in first
        assert first["source"] == "fixture"

    def test_avisa_quando_ha_dados_de_demonstracao(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["--json", "search", "redmi", "--source", "fixture"])
        payload = json.loads(result.output)
        assert any("demonstração" in warning for warning in payload["warnings"])

    def test_deduplica_mesmo_produto_entre_lojas(self, tmp_path: Path) -> None:
        result = _invoke(
            tmp_path,
            ["--json", "search", "Redmi Note 14 256GB", "--source", "fixture"],
        )
        payload = json.loads(result.output)
        product_ids = {item["product_id"] for item in payload["results"]}
        assert len(product_ids) == 1
        assert len(payload["results"]) > 1

    def test_picks_apontam_para_ofertas_existentes(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["--json", "search", "redmi", "--source", "fixture"])
        payload = json.loads(result.output)
        offer_ids = {item["offer_id"] for item in payload["results"]}

        assert payload["picks"]["best"] in offer_ids
        assert payload["picks"]["cheapest"] in offer_ids
        # Fase 1 nao inventa curadorias que dependem de analise futura.
        assert payload["picks"]["safest"] is None
        assert payload["picks"]["flash"] is None

    def test_sem_resultado_sai_com_codigo_3(self, tmp_path: Path) -> None:
        result = _invoke(
            tmp_path,
            ["search", "geladeira inox", "--source", "fixture", "--max-price", "100"],
        )
        assert result.exit_code == 3

    def test_saida_sem_unicode_usa_glyphs_ascii(self, tmp_path: Path) -> None:
        result = _invoke(
            tmp_path,
            ["--no-unicode", "search", "redmi", "--source", "fixture"],
        )
        assert result.exit_code == 0, result.output
        assert "[BEST]" in result.output
        assert "🏆" not in result.output

    def test_filtro_de_preco_aparece_no_resumo(self, tmp_path: Path) -> None:
        result = _invoke(
            tmp_path,
            ["search", "redmi", "--source", "fixture", "--max-price", "1650"],
        )
        assert result.exit_code == 0, result.output
        assert "Preço máximo" in result.output

    def test_fonte_desconhecida_gera_aviso_e_sem_fontes(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["--json", "search", "redmi", "--source", "inexistente"])
        payload = json.loads(result.output)
        assert result.exit_code == 3
        assert any("desconhecida" in warning for warning in payload["warnings"])


class TestHistory:
    def test_historico_apos_busca(self, tmp_path: Path) -> None:
        search = _invoke(
            tmp_path, ["--json", "search", "Redmi Note 14 256GB", "--source", "fixture"]
        )
        assert search.exit_code == 0, search.output

        result = _invoke(tmp_path, ["--json", "history", "redmi"])
        assert result.exit_code == 0, result.output

        payload = json.loads(result.output)
        assert payload["command"] == "history"
        assert payload["stats"]["samples"] >= 1
        assert payload["points"]
        assert payload["offers"]

    def test_historico_sem_dados_sai_com_codigo_3(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["history", "produto que nunca existiu"])
        assert result.exit_code == 3

    def test_historico_por_id_de_oferta(self, tmp_path: Path) -> None:
        search = _invoke(tmp_path, ["--json", "search", "redmi", "--source", "fixture"])
        offer_id = json.loads(search.output)["results"][0]["offer_id"]

        result = _invoke(tmp_path, ["--json", "history", offer_id])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["product"]["id"]
