"""Comandos ``dealhunter coupons``.

Cupom é dado declarado pela fonte. A simulação é local e explicitamente
rotulada; não há validação real junto à loja na Fase 2.
"""

from __future__ import annotations

from typing import Annotated

import typer

from dealhunter.cli.exit_codes import ExitCode
from dealhunter.cli.parsing import parse_money_option
from dealhunter.cli.render import emit_json
from dealhunter.cli.render.coupons import (
    check_payload,
    coupons_payload,
    render_coupon_check,
    render_coupons,
)
from dealhunter.cli.wiring import run_coupon_check, run_coupons_list
from dealhunter.domain.value_objects.money import Money
from dealhunter.runtime.container import RuntimeContext

app = typer.Typer(
    help="Cupons declarados pelas fontes (não são validados automaticamente).",
    no_args_is_help=True,
)


@app.command("list")
def list_command(
    ctx: typer.Context,
    store: Annotated[
        str | None, typer.Option("--store", help="Filtra por nome ou domínio da loja.")
    ] = None,
    show_all: Annotated[bool, typer.Option("--all", help="Inclui cupons expirados.")] = False,
) -> None:
    """Lista os cupons conhecidos a partir das coletas."""
    rt: RuntimeContext = ctx.obj
    rows = tuple(run_coupons_list(rt, store=store, include_expired=show_all))
    now = rt.clock.now()

    if rt.json_output:
        emit_json(coupons_payload(rows, now=now))
    else:
        render_coupons(rows, rt, now=now)

    if not rows:
        raise typer.Exit(code=int(ExitCode.NO_RESULTS))


@app.command("check")
def check_command(
    ctx: typer.Context,
    code: Annotated[str, typer.Argument(help="Código do cupom (ex.: AURORA10).")],
    price: Annotated[
        str,
        typer.Option("--price", help="Preço do produto para simular (ex.: 1649)."),
    ],
    shipping: Annotated[
        str | None, typer.Option("--shipping", help="Frete para incluir na simulação.")
    ] = None,
    store: Annotated[
        str | None, typer.Option("--store", help="Restringe a loja (nome ou domínio).")
    ] = None,
) -> None:
    """Simula localmente a aplicação de um cupom sobre um preço."""
    rt: RuntimeContext = ctx.obj
    price_cents = parse_money_option(price, option="--price")
    if price_cents is None:
        raise typer.BadParameter("--price é obrigatório")
    shipping_cents = parse_money_option(shipping, option="--shipping")

    outcomes = tuple(
        run_coupon_check(
            rt,
            code,
            price=Money(price_cents),
            shipping=Money(shipping_cents) if shipping_cents is not None else None,
            store=store,
        )
    )
    now = rt.clock.now()

    if rt.json_output:
        emit_json(
            check_payload(
                outcomes,
                now=now,
                price=Money(price_cents),
                shipping=Money(shipping_cents) if shipping_cents is not None else None,
            )
        )
    else:
        render_coupon_check(
            outcomes,
            rt,
            now=now,
            code=code,
            price=Money(price_cents),
            shipping=Money(shipping_cents) if shipping_cents is not None else None,
        )

    if not outcomes:
        raise typer.Exit(code=int(ExitCode.NO_RESULTS))
