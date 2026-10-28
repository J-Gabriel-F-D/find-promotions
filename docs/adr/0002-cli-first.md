# ADR 0002 — CLI-first, sem interface web no MVP

* Status: aceito
* Data: 2026-10-28

## Contexto

O requisito principal é uma ferramenta de terminal. Criar frontend web no MVP
adicionaria infraestrutura, autenticação de usuários e superfície de ataque sem
validar o núcleo do produto (coleta + confiança da oferta).

## Decisão

Toda a primeira versão é CLI. A camada `cli/` é somente apresentação e chama
casos de uso em `application/`. Nenhuma regra de negócio em comandos.

## Consequências

* **Positivas:** validação rápida do núcleo; zero infraestrutura; testável com
  `CliRunner`; uma futura API/web reutiliza os mesmos casos de uso sem duplicar
  lógica.
* **Negativas:** descoberta do produto depende do usuário saber operar terminal
  (mitigado por `interactive` e `--help` bem escrito).
* **Restrição arquitetural:** proibido importar `rich`/`typer` fora de `cli/`.
