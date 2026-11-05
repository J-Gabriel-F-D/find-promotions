"""Testes do REPL `dealhunter interactive` (sem shell escape)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from dealhunter.cli.app import app

runner = CliRunner()


def _invoke(tmp_path: Path, args: list[str], *, text: str):
    return runner.invoke(app, args, input=text, env={"DEALHUNTER_HOME": str(tmp_path / "home")})


class TestInteractive:
    def test_help_e_saida(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["interactive"], text="help\nsair\n")
        assert result.exit_code == 0, result.output
        assert "search <termo>" in result.output
        assert "Não há escape para shell" in result.output

    def test_eof_encerra_sem_erro(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["interactive"], text="")
        assert result.exit_code == 0, result.output

    def test_busca_na_fonte_fixture(self, tmp_path: Path) -> None:
        result = _invoke(
            tmp_path,
            ["interactive", "--source", "fixture"],
            text="search redmi note 14 256GB\nsair\n",
        )
        assert result.exit_code == 0, result.output
        assert "Loja Aurora" in result.output

    def test_reviews_no_repl(self, tmp_path: Path) -> None:
        result = _invoke(
            tmp_path,
            ["interactive", "--source", "fixture"],
            text="search redmi note 14 256GB\nreviews redmi\nsair\n",
        )
        assert result.exit_code == 0, result.output
        assert "Textos analisados" in result.output

    def test_historico_e_promocoes_no_repl(self, tmp_path: Path) -> None:
        result = _invoke(
            tmp_path,
            ["interactive", "--source", "fixture"],
            text=("search redmi note 14 256GB\nhistory redmi\npromotions\nsair\n"),
        )
        assert result.exit_code == 0, result.output
        assert "Histórico" in result.output or "histórico" in result.output
        assert "Promoções" in result.output or "promoções" in result.output

    def test_argumento_ausente_mostra_uso(self, tmp_path: Path) -> None:
        result = _invoke(
            tmp_path,
            ["interactive"],
            text="search\nreviews\nhistory\n\nsair\n",
        )
        assert result.exit_code == 0, result.output
        assert "uso: search <termo>" in result.output
        assert "uso: reviews <termo>" in result.output
        assert "uso: history <termo>" in result.output

    def test_quiet_e_rejeitado(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["--quiet", "interactive"], text="sair\n")
        assert result.exit_code == 2

    def test_comando_desconhecido_nao_executa_nada(self, tmp_path: Path) -> None:
        result = _invoke(
            tmp_path,
            ["interactive"],
            text="!whoami\npython -c print(1)\nsair\n",
        )
        assert result.exit_code == 0, result.output
        assert "comando desconhecido" in result.output
        assert "uid=" not in result.output

    def test_json_e_rejeitado(self, tmp_path: Path) -> None:
        result = _invoke(tmp_path, ["--json", "interactive"], text="sair\n")
        assert result.exit_code == 2
        assert "interactive" in result.output
