"""Comando ``dealhunter interactive``: REPL simples, sem shell escape."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.markup import escape

from dealhunter.application.intent import parse_query
from dealhunter.cli.render.history import render_history
from dealhunter.cli.render.promotions import render_promotions
from dealhunter.cli.render.reviews import render_reviews
from dealhunter.cli.render.search import render_search
from dealhunter.cli.wiring import (
    ensure_database,
    run_history,
    run_promotions,
    run_reviews,
    run_search,
)
from dealhunter.runtime.container import RuntimeContext

HELP = """Comandos disponíveis:
  search <termo>       busca ofertas nas fontes habilitadas
  reviews <termo>      agregado + análise determinística de textos
  history <termo>      histórico de preços do produto
  promotions           promoções com janela temporal
  help                 mostra esta ajuda
  sair | exit | quit   encerra o modo interativo

Não há escape para shell, eval ou execução de comandos do sistema."""


def _dispatch(rt: RuntimeContext, line: str, *, sources: list[str] | None) -> bool:
    command, _, argument = line.strip().partition(" ")
    command = command.lower()
    argument = argument.strip()

    if command in {"sair", "exit", "quit"}:
        return False
    if command in {"help", "?", "ajuda"}:
        rt.console.print(HELP)
        return True
    if not command:
        return True

    if command == "search":
        if not argument:
            rt.console.print("[yellow]uso: search <termo>[/yellow]")
            return True
        try:
            spec = parse_query(argument, default_limit=10)
        except ValueError as exc:
            rt.console.print(f"[yellow]{escape(str(exc))}[/yellow]")
            return True
        search_report = run_search(rt, spec, sources=sources)
        render_search(search_report, rt)
        return True

    if command == "reviews":
        if not argument:
            rt.console.print("[yellow]uso: reviews <termo>[/yellow]")
            return True
        review_report, warnings = run_reviews(rt, argument, text_limit=10)
        if review_report is None:
            for warning in warnings:
                rt.console.print(f"[yellow]{escape(warning)}[/yellow]")
        else:
            render_reviews(review_report, rt)
        return True

    if command == "history":
        if not argument:
            rt.console.print("[yellow]uso: history <termo>[/yellow]")
            return True
        history_report = run_history(rt, argument)
        if history_report is None:
            rt.console.print(f"[yellow]nada encontrado para: {escape(argument)}[/yellow]")
        else:
            render_history(history_report, rt)
        return True

    if command == "promotions":
        promotion_report = run_promotions(rt)
        render_promotions(promotion_report, rt)
        return True

    rt.console.print(f"[yellow]comando desconhecido: {escape(command)}. Digite 'help'.[/yellow]")
    return True


def interactive_command(
    ctx: typer.Context,
    source: Annotated[
        list[str] | None,
        typer.Option(
            "--source",
            "-s",
            help="Fonte específica para buscas (repetível). Ex.: fixture.",
        ),
    ] = None,
) -> None:
    """Abre um REPL simples; não executa comandos do sistema."""
    rt: RuntimeContext = ctx.obj
    if rt.json_output or rt.quiet:
        raise typer.BadParameter("interactive não combina com --json ou --quiet")

    ensure_database(rt)
    rt.console.print("[bold]DealHunter interativo[/bold] — digite 'help' ou 'sair'.")
    while True:
        try:
            line = input("dealhunter> ")
        except EOFError:
            rt.console.print()
            break
        except KeyboardInterrupt:
            rt.console.print()
            break
        if not _dispatch(rt, line, sources=source):
            break
