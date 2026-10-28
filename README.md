# DealHunter

CLI inteligente de **busca, comparação, análise de confiança e monitoramento de ofertas**.
Roda no terminal, sem servidor, sem Docker, sem dashboard web.

> O produto responde duas perguntas: **onde está o melhor preço agora** e **posso confiar nessa oferta?**

---

## Estado atual

| Fase | Escopo | Status |
|---|---|---|
| **0 — Fundação** | Estrutura, configuração, logging, banco + migrações, container, CLI base, `--json`, exit codes | ✅ concluída |
| 1 — MVP | `search`, fontes reais, normalização, histórico, `alerts`, e-mail | ⏳ próxima |
| 2 — Ofertas | cupons, promoções, ranking, avaliações | ⏳ |
| 3 — Confiança | antifraude, score, falso desconto, reclamações, `interactive` | ⏳ |
| 4 — Automação | `monitor` contínuo, WhatsApp/SMS, alertas inteligentes | ⏳ |

Decisões aprovadas: **Python 3.12+** · **Mercado Livre (API oficial) + fixture + adapter genérico** · **IA opcional com fallback determinístico**.

---

## Instalação (desenvolvimento)

```bash
py -3 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"   # Windows
# source .venv/bin/activate && pip install -e ".[dev]"   # Linux/macOS
```

Ou, em qualquer sistema, como ferramenta isolada:

```bash
pipx install -e .
# ou: uv tool install -e .
```

## Uso

```bash
dealhunter --help
dealhunter --version
dealhunter status
dealhunter db migrate
dealhunter config path
dealhunter config show
```

Saída para automação:

```bash
dealhunter --json status
```

```json
{
  "schema_version": "1.0",
  "command": "status",
  "generated_at": "2026-10-28T14:02:11+00:00",
  "version": "0.1.0",
  "database": { "initialized": true, "schema_version": "0001_init" }
}
```

## Flags globais

| Flag | Efeito |
|---|---|
| `--json` | Saída JSON no stdout (logs continuam no stderr) |
| `--quiet`, `-q` | Apenas eventos relevantes |
| `--debug` | Log detalhado, com segredos mascarados |
| `--no-color` | Desativa cores |
| `--no-unicode` | Força ASCII em terminais limitados |
| `--no-ai` | Desliga a IA mesmo se configurada |
| `--config PATH` | Usa um TOML específico |

### Exit codes

`0` ok · `1` erro · `2` uso inválido · `3` sem resultados · `4` sucesso parcial ·
`5` todas as fontes falharam · `6` erro de configuração · `130` interrompido.

---

## Configuração

Precedência: **flags** > **`DEALHUNTER_*`** > **`--config`** > **`./.dealhunter.toml`** > **config do usuário** > **defaults**.

Localização por sistema (via `platformdirs`):

| SO | Config |
|---|---|
| Windows | `%APPDATA%\dealhunter\config.toml` |
| macOS | `~/Library/Application Support/dealhunter/config.toml` |
| Linux | `$XDG_CONFIG_HOME/dealhunter/config.toml` |

`DEALHUNTER_HOME=./.dev` isola tudo em um diretório (útil para testes e perfis).

```toml
[general]
results_limit = 20
currency = "BRL"
timezone = "America/Sao_Paulo"

[search]
timeout_seconds = 20

[monitor]
interval_seconds = 600
quiet_hours_start = "22:00"
quiet_hours_end = "07:00"

[ai]
enabled = false

[sources]
enabled = ["mercadolivre", "fixture"]
respect_robots = true
```

**Segredos nunca vão no TOML** — apenas o nome da credencial no keyring ou da variável de ambiente.

---

## Arquitetura

Arquitetura hexagonal: `cli → application → domain ← adapters`.

```
src/dealhunter/
├─ cli/            # Typer + Rich: comandos, render, ui
├─ domain/         # modelos, value objects, políticas, portas
├─ application/    # casos de uso, DTOs, orquestradores
├─ adapters/       # sources, http, storage, notify, ai
├─ services/       # normalizer, pricing, coupons, reviews, fraud, ranking
├─ runtime/        # config, logging, container, jobs
└─ data/           # migrations, prompts, sources.yaml
```

Documento completo: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
Decisões registradas: [`docs/adr`](docs/adr).

## Testes

```bash
.venv\Scripts\python -m pytest
```

## Princípios

1. **Nunca inventar dados.** Preço, cupom, loja e reputação vêm de fonte verificável; a IA não os gera.
2. **Toda informação tem origem e data.** `source`, `source_url`, `collected_at`, `last_verified_at`, `confidence`.
3. **Suspeita ≠ fraude.** Linguagem sempre probabilística, com evidências expostas.
4. **Desconto da loja não é verdade.** Comparado com o histórico coletado pela própria ferramenta.
5. **Uma fonte fora do ar não derruba a busca.**
6. **Sem burlar proteções.** robots.txt, termos de uso, limites de requisição e APIs oficiais.
7. **CLI-first.** Nenhuma lógica de negócio dentro dos comandos.

## Licença

Proprietária. Todos os direitos reservados.
