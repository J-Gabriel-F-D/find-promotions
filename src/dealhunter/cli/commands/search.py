"""Comando ``dealhunter search``."""

from __future__ import annotations

from typing import Annotated

import typer

from dealhunter.application.dto import QuerySpec
from dealhunter.application.intent import parse_query
from dealhunter.cli.exit_codes import ExitCode
from dealhunter.cli.parsing import parse_capacity_option, parse_money_option
from dealhunter.cli.render import emit_json
from dealhunter.cli.render.search import render_search, search_payload
from dealhunter.cli.wiring import run_search
from dealhunter.runtime.container import RuntimeContext


def search_command(
    ctx: typer.Context,
    query: Annotated[
        str | None,
        typer.Argument(help="Busca em linguagem natural (ex.: 'Redmi Note 256GB ate R$1800')."),
    ] = None,
    product: Annotated[str | None, typer.Option("--product", "-p", help="Produto.")] = None,
    brand: Annotated[str | None, typer.Option("--brand", help="Marca.")] = None,
    category: Annotated[str | None, typer.Option("--category", help="Categoria.")] = None,
    max_price: Annotated[
        str | None, typer.Option("--max-price", help="Preço máximo (ex.: 1800 ou 'R$ 1.800,00').")
    ] = None,
    min_price: Annotated[str | None, typer.Option("--min-price", help="Preço mínimo.")] = None,
    storage: Annotated[
        str | None, typer.Option("--storage", help="Armazenamento (ex.: 256GB).")
    ] = None,
    ram: Annotated[str | None, typer.Option("--ram", help="RAM minima (ex.: 16GB).")] = None,
    condition: Annotated[
        str, typer.Option("--condition", help="new | used | any", case_sensitive=False)
    ] = "new",
    exclude_store: Annotated[
        list[str] | None, typer.Option("--exclude-store", help="Loja a ignorar (repetivel).")
    ] = None,
    source: Annotated[
        list[str] | None,
        typer.Option("--source", "-s", help="Fonte específica (repetivel). Ex.: fixture."),
    ] = None,
    sort: Annotated[
        str, typer.Option("--sort", help="best | price | reputation", case_sensitive=False)
    ] = "best",
    limit: Annotated[
        int, typer.Option("--limit", min=1, max=200, help="Máximo de resultados.")
    ] = 20,
) -> None:
    """Busca ofertas em todas as fontes habilitadas."""
    rt: RuntimeContext = ctx.obj

    try:
        if query:
            spec = parse_query(query, default_limit=limit)
        elif product or brand or category:
            spec = QuerySpec(
                product=product or "",
                brand=brand,
                category=category,
                limit=limit,
            )
        else:
            raise typer.BadParameter("informe uma busca livre ou ao menos --product/--brand")
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    overrides = {
        "max_price_cents": parse_money_option(max_price, option="--max-price"),
        "min_price_cents": parse_money_option(min_price, option="--min-price"),
        "storage_gb": parse_capacity_option(storage, option="--storage"),
        "ram_gb": parse_capacity_option(ram, option="--ram"),
        "condition": condition.lower(),
        "sort": sort.lower(),
        "limit": limit,
        "exclude_stores": exclude_store or [],
    }
    merged = {**spec.model_dump(), **{k: v for k, v in overrides.items() if v is not None}}
    try:
        spec = QuerySpec.model_validate(merged)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    if rt.json_output or rt.quiet:
        report = run_search(rt, spec, sources=source)
    else:
        with rt.console.status("[cyan]Consultando fontes...[/cyan]", spinner="dots"):
            report = run_search(rt, spec, sources=source)

    if rt.json_output:
        emit_json(search_payload(report))
    elif rt.quiet:
        if report.views:
            best = report.views[0]
            rt.console.print(
                f"{best.offer.final_price} | {best.store.name} | "
                f"{best.product.title} | {best.offer.url}",
                soft_wrap=True,
            )
    else:
        render_search(report, rt)

    if not report.views:
        failed = [status for status in report.sources if status.status in {"error", "timeout"}]
        if report.sources and len(failed) == len(report.sources):
            raise typer.Exit(code=int(ExitCode.ALL_SOURCES_FAILED))
        raise typer.Exit(code=int(ExitCode.NO_RESULTS))
    if any(status.status in {"error", "timeout"} for status in report.sources):
        raise typer.Exit(code=int(ExitCode.PARTIAL_FAILURE))
