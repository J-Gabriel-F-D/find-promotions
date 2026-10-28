# ADR 0003 — SQLite local-first, sem Redis

* Status: aceito
* Data: 2026-10-28

## Contexto

A aplicação roda na máquina do usuário. Exigir PostgreSQL e Redis para uma CLI
de desktop aumentaria o custo de instalação a ponto de inviabilizar adoção.

## Decisão

SQLite em modo WAL como banco padrão. Scheduler asyncio in-process com tabela
`job` persistida. Nenhum broker externo.

## Consequências

* **Positivas:** instalação trivial, backup = copiar arquivo, zero ops, WAL
  permite leitura concorrente durante escrita.
* **Negativas:** escritor único (aceitável: um monitor por máquina, garantido por
  lock de arquivo); sem acesso concorrente por rede.
* **Caminho de saída:** todo SQL fica em `adapters/storage/`; trocar para
  PostgreSQL é substituir a implementação dos repositórios, sem tocar no
  domínio.
* `offer_snapshot` é append-only para que o histórico nunca seja reescrito.
