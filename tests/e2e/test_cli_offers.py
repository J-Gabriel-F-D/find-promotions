"""Testes ponta a ponta de cupons, promoções e avaliações."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from dealhunter.cli.app import app

runner = CliRunner()


def _invoke(tmp_path: Path, args: list[str]):
    return runner.invoke(app, args, env={"DEALHUNTER_HOME": str(tmp_path / "home")})


def _search(tmp_path: Path, term: str) -> None:
    result = _invoke(tmp_path, ["--json", "search", term, "--source", "fixture"])
    assert result.exit_code == 0, result.output


class TestCuponsNaBusca:
    def test_oferta_traz_cupom_estimado_sem_alterar_preco_confirmado(self, tmp_path: Path) -> None:
        _search(tmp_path, "redmi note 14 256GB")
        result = _invoke(
            tmp_path, ["--json", "search", "redmi note 14 256GB", "--source", "fixture"]
        )
        payload = json.loads(result.output)
        aurora = next(item for item in payload["results"] if item["store"]["name"] == "Loja Aurora")

        assert aurora["price_cents"] == 164_900
        assert aurora["final_price_cents"] == 164_900  # confirmado, sem cupom
        assert aurora["best_coupon"]["code"] == "AURORA10"
        assert aurora["best_coupon"]["validation"] == "unverified"
        assert aurora["best_coupon"]["applicable"] is True
        assert aurora["estimated_final_price_with_coupon_cents"] == 148_410

    def test_cupom_sem_minimo_atingido_nao_entra_no_melhor(self, tmp_path: Path) -> None:
        _search(tmp_path, "redmi note 14 256GB")
        result = _invoke(
            tmp_path, ["--json", "search", "redmi note 14 256GB", "--source", "fixture"]
        )
        payload = json.loads(result.output)
        importafacil = next(
            item for item in payload["results"] if item["store"]["name"] == "ImportaFacil"
        )

        assert importafacil["best_coupon"] is None
        assert importafacil["estimated_final_price_with_coupon_cents"] is None
        assert importafacil["coupons"][0]["applicable"] is False
        assert "valor mínimo" in importafacil["coupons"][0]["reason"]


class TestComandoCupons:
    def test_lista_cupons_coletados(self, tmp_path: Path) -> None:
        _search(tmp_path, "redmi")
        result = _invoke(tmp_path, ["--json", "coupons", "list"])
        assert result.exit_code == 0, result.output

        payload = json.loads(result.output)
        assert payload["command"] == "coupons.list"
        assert payload["count"] >= 1
        codes = {item["code"] for item in payload["coupons"]}
        assert "AURORA10" in codes
        assert all(item["validation"] == "unverified" for item in payload["coupons"])
        assert any("validado" in warning for warning in payload["warnings"])

    def test_lista_vazia_sai_com_codigo_3(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["coupons", "list"])
        assert result.exit_code == 3

    def test_check_simula_desconto(self, tmp_path: Path) -> None:
        _search(tmp_path, "redmi")
        result = _invoke(
            tmp_path,
            ["--json", "coupons", "check", "AURORA10", "--price", "1649", "--shipping", "0"],
        )
        assert result.exit_code == 0, result.output

        payload = json.loads(result.output)
        item = payload["results"][0]
        assert payload["command"] == "coupons.check"
        assert item["applicable"] is True
        assert item["estimated_discount_cents"] == 16_490
        assert item["estimated_final_price_cents"] == 148_410
        assert item["estimate"] is True
        assert item["validation_method"] == "local_rules"

    def test_check_de_cupom_desconhecido_sai_com_codigo_3(self, tmp_path: Path) -> None:
        _search(tmp_path, "redmi")
        result = _invoke(tmp_path, ["--json", "coupons", "check", "NAOEXISTE", "--price", "100"])
        assert result.exit_code == 3
        assert json.loads(result.output)["results"] == []

    def test_all_inclui_cupom_expirado(self, tmp_path: Path) -> None:
        _search(tmp_path, "ideapad")
        default = _invoke(tmp_path, ["--json", "coupons", "list"])
        everything = _invoke(tmp_path, ["--json", "coupons", "list", "--all"])

        default_codes = {item["code"] for item in json.loads(default.output)["coupons"]}
        all_codes = {item["code"] for item in json.loads(everything.output)["coupons"]}
        assert "MEGA10" not in default_codes
        assert "MEGA10" in all_codes
        expired = next(
            item for item in json.loads(everything.output)["coupons"] if item["code"] == "MEGA10"
        )
        assert expired["state"] == "expired"


class TestComandoPromocoes:
    def test_lista_promocoes_ativas(self, tmp_path: Path) -> None:
        _search(tmp_path, "redmi")
        result = _invoke(tmp_path, ["--json", "promotions"])
        assert result.exit_code == 0, result.output

        payload = json.loads(result.output)
        assert payload["command"] == "promotions"
        assert payload["count"] >= 1
        assert all(item["state"] == "active" for item in payload["promotions"])
        assert any(item["kind"] == "flash" for item in payload["promotions"])
        assert all(item["ends_at"] for item in payload["promotions"])

    def test_filtra_por_janela(self, tmp_path: Path) -> None:
        _search(tmp_path, "redmi")
        result = _invoke(tmp_path, ["--json", "promotions", "--expiring-in", "4"])
        payload = json.loads(result.output)
        assert payload["count"] >= 1
        assert all(item["remaining"].startswith("termina em") for item in payload["promotions"])

    def test_sem_promocoes_sai_com_codigo_3(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["promotions"])
        assert result.exit_code == 3


class TestComandoAvaliacoes:
    def test_mostra_agregado_da_fonte(self, tmp_path: Path) -> None:
        _search(tmp_path, "redmi note 14 256GB")
        result = _invoke(tmp_path, ["--json", "reviews", "redmi"])
        assert result.exit_code == 0, result.output

        payload = json.loads(result.output)
        assert payload["command"] == "reviews"
        assert payload["sources"]
        source = payload["sources"][0]
        assert 0 <= source["rating"] <= 5
        assert source["count"] > 0
        assert "distribution" in source
        assert any("Fase 3" in warning for warning in payload["warnings"])

    def test_produto_sem_avaliacao_sai_com_codigo_3(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["reviews", "produto que nunca existiu"])
        assert result.exit_code == 3

    def test_saida_humana_inclui_estrelas(self, tmp_path: Path) -> None:
        _search(tmp_path, "redmi note 14 256GB")
        result = _invoke(tmp_path, ["reviews", "redmi"])
        assert result.exit_code == 0, result.output
        assert "avaliações" in result.output
        assert "5★" in result.output
