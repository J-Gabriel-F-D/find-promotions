# ADR 0001 — Python 3.12+ como linguagem do projeto

* Status: aceito
* Data: 2026-10-28

## Contexto

O produto é uma CLI local que coleta dados de múltiplas fontes, normaliza nomes
de produtos, calcula estatísticas de preço, analisa texto (avaliações e
reclamações) e opcionalmente usa LLM. O gargalo é I/O e processamento de texto,
não CPU. Precisa rodar em Windows, macOS e Linux.

## Alternativas

1. **Python 3.12 + Typer/Rich** — ecossistema mais denso em scraping, parsing,
   normalização e IA; Pydantic valida contratos; um processo dispensa Redis.
2. **Go 1.23 + Cobra/Bubble Tea** — binário único e startup instantâneo, mas
   ecossistema pobre para normalização/IA; ~1,6× mais esforço no MVP.
3. **Node/TypeScript + Ink** — boa TUI, porém exige runtime Node e empacotamento
   pior.

## Decisão

Python 3.12+ (validado em 3.14).

## Consequências

* **Positivas:** Pydantic na fronteira impede dado inválido circular; Rich
  entrega a UX pedida; `pytest` + `respx` + `hypothesis` cobrem unit, contrato e
  property-based; distribuição via `pipx`/`uv tool`.
* **Negativas:** startup ~300 ms (mitigável com imports tardios); binário único
  exige PyInstaller/Nuitka; GIL irrelevante (carga é I/O-bound).
* Se distribuição como binário virar requisito rígido, o core é puro o
  suficiente para permitir um porte incremental sem reescrever o domínio.
