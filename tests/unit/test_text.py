"""Testes de normalizacao de texto e extracao de especificacoes."""

from __future__ import annotations

import pytest

from dealhunter.services.text import (
    build_identity,
    detect_brand,
    detect_category,
    model_family,
    normalize_text,
    parse_ram_gb,
    parse_screen_inches,
    parse_storage_gb,
)


class TestNormalize:
    def test_remove_acento_e_pontuacao(self) -> None:
        assert normalize_text("Notebook PROGRAMAÇÃO, 16GB!") == "notebook programacao 16gb"

    def test_colapsa_espacos(self) -> None:
        assert normalize_text("  a   b  ") == "a b"


class TestBrandAndCategory:
    @pytest.mark.parametrize(
        ("title", "brand"),
        [
            ("Xiaomi Redmi Note 14 256GB", "xiaomi"),
            ("Samsung Galaxy S24", "samsung"),
            ("Apple iPhone 16 128GB", "apple"),
            ("Notebook Lenovo IdeaPad 3", "lenovo"),
            ("Placa de Video NVIDIA RTX 4070", "nvidia"),
        ],
    )
    def test_detecta_marca(self, title: str, brand: str) -> None:
        assert detect_brand(title) == brand

    def test_marca_desconhecida(self) -> None:
        assert detect_brand("Cadeira de escritorio ergonomica") is None

    @pytest.mark.parametrize(
        ("title", "category"),
        [
            ("Celular Samsung Galaxy", "smartphone"),
            ("Notebook para programacao", "notebook"),
            ("Placa de video RTX 4070", "gpu"),
            ("Tablet iPad", "tablet"),
        ],
    )
    def test_detecta_categoria(self, title: str, category: str) -> None:
        assert detect_category(title) == category


class TestSpecs:
    @pytest.mark.parametrize(
        ("text", "gb"),
        [
            ("Redmi Note 256GB", 256),
            ("SSD de 512 GB", 512),
            ("1TB de armazenamento", 1024),
            ("sem capacidade informada", None),
        ],
    )
    def test_armazenamento(self, text: str, gb: int | None) -> None:
        assert parse_storage_gb(text) == gb

    def test_armazenamento_ignora_valor_da_ram(self) -> None:
        assert parse_storage_gb("8 GB de RAM, 256 GB") == 256
        assert parse_storage_gb("16GB RAM 512GB SSD") == 512

    @pytest.mark.parametrize(
        ("text", "ram"),
        [
            ("8 GB de RAM", 8),
            ("com 16GB RAM", 16),
            ("RAM 12 GB", 12),
            ("sem ram", None),
        ],
    )
    def test_ram(self, text: str, ram: int | None) -> None:
        assert parse_ram_gb(text) == ram

    @pytest.mark.parametrize(
        ("text", "inches"),
        [('tela de 6,5"', 6.5), ("tela 6.1 polegadas", 6.1), ("sem tela", None)],
    )
    def test_tela(self, text: str, inches: float | None) -> None:
        assert parse_screen_inches(text) == inches


class TestIdentity:
    def test_gtin_tem_prioridade(self) -> None:
        kind, value = build_identity(
            title="Qualquer coisa", brand="samsung", storage_gb=256, ram_gb=8, gtin="7891234567895"
        )
        assert kind == "gtin"
        assert value == "7891234567895"

    def test_mpn_com_marca(self) -> None:
        kind, value = build_identity(
            title="Galaxy", brand="samsung", storage_gb=None, ram_gb=None, mpn="SM-S921B"
        )
        assert kind == "mpn"
        assert value == "samsung:sm s921b"

    def test_modelo_com_marca_familia_e_capacidade(self) -> None:
        kind, value = build_identity(
            title="Xiaomi Redmi Note 14 256GB 8GB RAM Preto",
            brand="xiaomi",
            storage_gb=256,
            ram_gb=8,
        )
        assert kind == "model"
        assert value == "xiaomi|redmi note 14|256|ram8"

    def test_sem_dados_suficientes_cai_para_titulo(self) -> None:
        kind, _ = build_identity(
            title="Capinha para celular", brand=None, storage_gb=None, ram_gb=None
        )
        assert kind == "title"

    def test_familia_remove_ruido_de_marketing(self) -> None:
        assert (
            model_family("Xiaomi Redmi Note 14 256GB 8GB RAM Preto Lacrado Original", "xiaomi")
            == "redmi note 14"
        )
