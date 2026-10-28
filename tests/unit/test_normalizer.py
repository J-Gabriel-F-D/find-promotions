"""Testes de normalizacao e deduplicacao de produtos."""

from __future__ import annotations

from dealhunter.domain.models import CollectedOffer
from dealhunter.services.normalizer import ProductNormalizer


def _collected(**overrides: object) -> CollectedOffer:
    base: dict[str, object] = {
        "source_id": "fixture",
        "title": "Xiaomi Redmi Note 14 256GB 8GB RAM 5G",
        "url": "https://loja.example/p",
        "source_url": "https://loja.example/p",
        "price_cents": 150_000,
        "store_name": "Loja Teste",
        "store_domain": "loja.example",
    }
    base.update(overrides)
    return CollectedOffer(**base)  # type: ignore[arg-type]


class TestDedupe:
    def test_titulos_equivalentes_geram_mesmo_produto(self) -> None:
        normalizer = ProductNormalizer()
        first = normalizer.to_product(_collected())
        second = normalizer.to_product(
            _collected(title="Smartphone Xiaomi Redmi Note 14 256GB", specs={"memoria_ram": "8GB"})
        )
        assert first.id == second.id
        assert first.identity_kind == "model"

    def test_capacidades_diferentes_nao_sao_o_mesmo_produto(self) -> None:
        normalizer = ProductNormalizer()
        first = normalizer.to_product(_collected())
        second = normalizer.to_product(_collected(title="Xiaomi Redmi Note 14 128GB 8GB RAM"))
        assert first.id != second.id

    def test_gtin_tem_prioridade_sobre_titulo(self) -> None:
        normalizer = ProductNormalizer()
        first = normalizer.to_product(_collected(gtin="7891234567895"))
        second = normalizer.to_product(
            _collected(title="Outro titulo completamente diferente", gtin="7891234567895")
        )
        assert first.id == second.id
        assert first.identity_kind == "gtin"

    def test_titulos_parecidos_sem_evidencia_nao_sao_fundidos(self) -> None:
        normalizer = ProductNormalizer()
        first = normalizer.to_product(_collected(title="Capinha para celular", brand=None))
        second = normalizer.to_product(
            _collected(title="Capinha para celular transparente", brand=None)
        )
        assert first.id != second.id
        assert first.identity_kind == "title"

    def test_variacao_de_processador_nao_quebra_identidade(self) -> None:
        normalizer = ProductNormalizer()
        first = normalizer.to_product(
            _collected(title="Notebook Lenovo IdeaPad 3 Ryzen 5 16GB RAM SSD 512GB")
        )
        second = normalizer.to_product(_collected(title="Notebook Lenovo IdeaPad 3 16GB 512GB SSD"))
        assert first.family == "ideapad 3"
        assert first.id == second.id

    def test_variacao_de_placa_de_video_nao_quebra_identidade(self) -> None:
        normalizer = ProductNormalizer()
        first = normalizer.to_product(
            _collected(title="Placa de Video NVIDIA GeForce RTX 4070 12GB GDDR6X")
        )
        second = normalizer.to_product(_collected(title="Placa de Video RTX 4070 12GB"))
        assert first.family == "rtx 4070"
        assert first.id == second.id


class TestAtributos:
    def test_extrai_marca_e_capacidades_do_titulo(self) -> None:
        product = ProductNormalizer().to_product(_collected())
        assert product.brand == "xiaomi"
        assert product.storage_gb == 256
        assert product.ram_gb == 8

    def test_preserva_especificacoes_da_fonte(self) -> None:
        product = ProductNormalizer().to_product(
            _collected(specs={"armazenamento": "512GB", "processador": "Ryzen 5"})
        )
        assert product.storage_gb == 512
        assert product.specs["processador"] == "Ryzen 5"
