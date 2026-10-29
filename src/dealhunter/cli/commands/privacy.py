"""Comandos de privacidade: exportação, esquecimento e retenção."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.markup import escape

from dealhunter.adapters.storage.repository import SqliteRepository
from dealhunter.application.use_cases.privacy import PrivacyService
from dealhunter.cli.exit_codes import ExitCode
from dealhunter.cli.render import emit_json, envelope
from dealhunter.cli.wiring import ensure_database
from dealhunter.runtime.config import mask_config_pii
from dealhunter.runtime.container import RuntimeContext

app = typer.Typer(
    help="Exporta, esquece ou aplica retenção aos seus dados locais.",
    no_args_is_help=True,
)


def _service(rt: RuntimeContext) -> PrivacyService:
    ensure_database(rt)
    return PrivacyService(SqliteRepository(rt.database))


def _profile(rt: RuntimeContext, *, include_contacts: bool = False) -> dict[str, Any]:
    profile = rt.config if include_contacts else mask_config_pii(rt.config)
    return {
        "notifications": {
            "channels": list(profile.notifications.channels),
            "email_from": profile.notifications.email_from,
            "email_to": profile.notifications.email_to,
        },
        "privacy": {"retention_days": profile.privacy.retention_days},
    }


def _export_payload(rt: RuntimeContext, *, include_contacts: bool = False) -> dict[str, Any]:
    report = _service(rt).export(rt.clock.now())
    return envelope(
        "privacy.export",
        generated_at=report.generated_at.isoformat(),
        counts=report.counts,
        profile=_profile(rt, include_contacts=include_contacts),
        alerts=list(report.alerts),
        events=list(report.events),
        notifications=list(report.notifications),
    )


@app.command("export")
def export(
    ctx: typer.Context,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Grava o JSON em um arquivo privado."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Sobrescreve o arquivo de saída, se existir."),
    ] = False,
    include_contacts: Annotated[
        bool,
        typer.Option(
            "--include-contacts",
            help="Inclui e-mails reais no perfil; por padrão eles são mascarados.",
        ),
    ] = False,
) -> None:
    """Exporta alertas, eventos e metadados de notificação em JSON."""
    rt: RuntimeContext = ctx.obj
    payload = _export_payload(rt, include_contacts=include_contacts)
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)

    if output is not None:
        if output.exists() and not force:
            rt.error_console.print(
                f"[red]O arquivo já existe: {escape(str(output))}. Use --force.[/red]"
            )
            raise typer.Exit(code=int(ExitCode.ERROR))
        output.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(output, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        if os.name != "nt":
            output.chmod(0o600)
        if rt.json_output:
            emit_json(
                envelope(
                    "privacy.export",
                    generated_at=payload["generated_at"],
                    output=str(output),
                    counts=payload["counts"],
                )
            )
        else:
            rt.console.print(
                f"[green]Exportação gravada em {escape(str(output))}[/green] "
                f"({payload['counts']['alerts']} alerta(s))."
            )
        return

    if rt.json_output:
        emit_json(payload)
        return

    counts = payload["counts"]
    rt.console.print("[bold]Exportação de dados pessoais[/bold]")
    rt.console.print(f"Alertas: {counts['alerts']}")
    rt.console.print(f"Eventos: {counts['events']}")
    rt.console.print(f"Notificações: {counts['notifications']}")
    rt.console.print(
        "[dim]Use --json para o conteúdo completo ou --output ARQUIVO para "
        "gravar uma cópia privada.[/dim]"
    )


@app.command("forget")
def forget(
    ctx: typer.Context,
    yes: Annotated[
        bool,
        typer.Option("--yes", help="Confirma a exclusão irreversível."),
    ] = False,
) -> None:
    """Apaga alertas, eventos e notificações do banco local."""
    rt: RuntimeContext = ctx.obj
    if not yes:
        raise typer.BadParameter("confirme com --yes para apagar os dados pessoais")
    counts = _service(rt).forget()
    if rt.json_output:
        emit_json(
            envelope(
                "privacy.forget",
                generated_at=rt.clock.now().isoformat(),
                deleted=counts,
            )
        )
        return
    rt.console.print(
        "[green]Dados apagados:[/green] "
        f"{counts['alerts']} alerta(s), {counts['events']} evento(s), "
        f"{counts['notifications']} notificação(ões)."
    )


@app.command("retention")
def retention(
    ctx: typer.Context,
    days: Annotated[
        int | None,
        typer.Option("--days", min=1, max=3650, help="Janela de retenção em dias."),
    ] = None,
    apply: Annotated[
        bool,
        typer.Option("--apply", help="Executa a exclusão; sem isso, apenas simula."),
    ] = False,
) -> None:
    """Remove eventos/notificações mais antigos que a janela configurada."""
    rt: RuntimeContext = ctx.obj
    window = days if days is not None else rt.config.privacy.retention_days
    result = _service(rt).retention(days=window, now=rt.clock.now(), apply=apply)

    if rt.json_output:
        emit_json(
            envelope(
                "privacy.retention",
                generated_at=rt.clock.now().isoformat(),
                days=result.days,
                cutoff=result.cutoff.isoformat(),
                applied=result.applied,
                counts=result.counts,
            )
        )
        return

    verb = "removidos" if apply else "seriam removidos"
    rt.console.print(
        f"[bold]Retenção de {result.days} dia(s)[/bold] "
        f"até {result.cutoff.strftime('%d/%m/%Y %H:%M')} UTC: "
        f"{result.counts['events']} evento(s) e "
        f"{result.counts['notifications']} notificação(ões) {verb}."
    )
    if not apply:
        rt.console.print("[dim]Use --apply para executar a exclusão.[/dim]")
