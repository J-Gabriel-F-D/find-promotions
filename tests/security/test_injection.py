"""Injeção, markup, path traversal e chamadas perigosas."""

from __future__ import annotations

import io
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from rich.console import Console
from typer.testing import CliRunner

from dealhunter.adapters.storage.repository import SqliteRepository
from dealhunter.application.dto import QuerySpec, SearchReport
from dealhunter.cli.app import app
from dealhunter.cli.render.search import render_search
from dealhunter.cli.ui.glyphs import glyphs_for
from dealhunter.domain.models import (
    DiscountAssessment,
    Offer,
    OfferView,
    Product,
    Store,
)
from dealhunter.domain.value_objects.money import Money

runner = CliRunner()


def _invoke(tmp_path: Path, args: list[str]):
    return runner.invoke(app, args, env={"DEALHUNTER_HOME": str(tmp_path / "home")})


def _malicious_report(title: str, *, store: str = "[red]Loja[/red]") -> SearchReport:
    product = Product(title=title, identity_kind="title", identity_value=title)
    shop = Store(name=store, domain="loja.example", source="fixture")
    offer = Offer(
        product_id=product.id,
        store_id=shop.id,
        seller_id=None,
        url="javascript:alert(1)",
        source="fixture",
        source_url="https://loja.example/feed",
        price=Money(100_000),
        collected_at=datetime(2026, 3, 15, 12, tzinfo=UTC),
    )
    view = OfferView(
        offer=offer,
        product=product,
        store=shop,
        seller=None,
        stats=None,
        discount=DiscountAssessment("normal", "<script>alert(1)</script>"),
        deal_score=50,
        flags=(),
    )
    return SearchReport(
        spec=QuerySpec(raw="<script>alert(1)</script>"),
        views=(view,),
        sources=(),
        collected=1,
        discarded=0,
        discard_reasons={},
        picks={},
    )


def _render(report: SearchReport) -> str:
    output = io.StringIO()
    console = Console(
        file=output,
        no_color=True,
        force_terminal=False,
        width=200,
        highlight=False,
    )
    render_search(report, SimpleNamespace(console=console, glyphs=glyphs_for(True)))
    return output.getvalue()


class TestSqlInjection:
    def test_termo_malicioso_nao_altera_schema(self, database) -> None:
        repo = SqliteRepository(database)
        term = "'; DROP TABLE product; --"
        assert repo.find_products(term) == []
        with database.connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM product").fetchone()[0]
        assert count == 0

    def test_codigo_de_cupom_malicioso_e_parameterizado(self, database, clock) -> None:
        repo = SqliteRepository(database)
        assert repo.find_coupons_by_code("' OR 1=1 --") == []
        with database.connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM coupon").fetchone()[0] == 0
        assert clock is not None

    def test_busca_cli_com_sql_injection_nao_derruba_o_banco(self, tmp_path: Path) -> None:
        result = _invoke(
            tmp_path,
            ["search", "redmi'); DROP TABLE product; --", "--source", "fixture"],
        )
        assert result.exit_code in {0, 3}
        # O comando seguinte continua funcionando (tabelas intactas).
        status = _invoke(tmp_path, ["--json", "db", "info"])
        assert status.exit_code == 0, status.output


class TestCommandAndPathInjection:
    def test_codigo_nao_chama_comandos_do_sistema(self) -> None:
        root = Path(__file__).resolve().parents[2] / "src" / "dealhunter"
        forbidden = re.compile(
            r"\b(subprocess\.|os\.system\s*\(|os\.popen\s*\(|shell\s*=\s*True|"
            r"pickle\.loads\s*\(|yaml\.load\s*\(|eval\s*\(|exec\s*\()"
        )
        offenders = [
            str(path.relative_to(root))
            for path in root.rglob("*.py")
            if forbidden.search(path.read_text(encoding="utf-8"))
        ]
        assert offenders == []

    def test_nome_de_produto_com_traversal_nao_cria_arquivos(self, tmp_path: Path) -> None:
        marker = "traversal_marker_7f3a"
        result = _invoke(
            tmp_path,
            ["search", f"../../{marker}", "--source", "fixture"],
        )
        assert result.exit_code in {0, 3}
        assert list(tmp_path.rglob(f"*{marker}*")) == []

    def test_argumento_com_hifen_nao_vira_comando(self, tmp_path: Path) -> None:
        result = _invoke(
            tmp_path,
            ["search", "--source", "fixture", "--", "--max-price; whoami"],
        )
        assert result.exit_code in {0, 3}
        assert "uid=" not in result.output


class TestMarkupAndXss:
    def test_markup_no_produto_e_escapado(self) -> None:
        output = _render(_malicious_report("[bold red]NÃO CLIQUE[/bold red]"))
        assert "\x1b[" not in output
        assert "[bold red]NÃO CLIQUE[/bold red]" in output

    def test_html_e_escapado_como_texto(self) -> None:
        output = _render(_malicious_report("<script>alert(1)</script>"))
        assert "<script>alert(1)</script>" in output
        assert "\x1b[" not in output

    def test_template_injection_nao_e_avaliado(self) -> None:
        output = _render(_malicious_report("{{7*7}} ${7*7} {% if true %}x{% endif %}"))
        assert "{{7*7}}" in output
        assert "49" not in output
        assert "{% if true %}x{% endif %}" in output

    def test_markup_em_aviso_de_notificacao_e_escapado(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        config = home / "config" / "config.toml"
        config.parent.mkdir(parents=True)
        config.write_text(
            '[notifications]\nchannels = ["console", "[red]sms[/red]"]\n', encoding="utf-8"
        )

        result = _invoke(tmp_path, ["notify", "status"])
        assert result.exit_code == 0, result.output
        assert "\x1b[" not in result.output
        assert "[red]sms[/red]" in result.output

    def test_html_em_json_permanece_dado_e_nao_executa(self, tmp_path: Path) -> None:
        result = _invoke(
            tmp_path,
            ["--json", "search", "<script>alert(1)</script>", "--source", "fixture"],
        )
        assert result.exit_code in {0, 3}
        if result.exit_code == 0:
            payload = json.loads(result.output)
            assert payload["query"]["raw"] == "<script>alert(1)</script>"
            assert "\x1b[" not in result.output
