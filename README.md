# DealHunter

CLI inteligente de **busca, comparação, análise de confiança e monitoramento de ofertas**.
Roda no terminal, sem servidor, sem Docker, sem dashboard web.

> O produto responde duas perguntas: **onde está o melhor preço agora** e **posso confiar nessa oferta?**

---

## Estado atual

| Fase | Escopo | Status |
|---|---|---|
| **0 — Fundação** | Estrutura, configuração, logging, banco + migrações, container, CLI base, `--json`, exit codes | ✅ concluída |
| **1 — MVP** | `search`, fontes (Mercado Livre + feed + fixture), normalização/dedupe, histórico, `alerts`, e-mail | ✅ concluída |
| 2 — Ofertas | cupons, promoções, ranking por promoção, avaliações | ⏳ |
| 3 — Confiança | antifraude, score de confiança, falso desconto, reclamações, `interactive` | ⏳ |
| 4 — Automação | `monitor` contínuo, WhatsApp/SMS, alertas inteligentes | ⏳ |

Decisões aprovadas: **Python 3.12+** · **Mercado Livre (API oficial) + fixture + adapter genérico** · **IA opcional com fallback determinístico**.

### O que a Fase 1 faz

- Busca em linguagem natural (`"Redmi Note 256GB até R$1800"`) ou por flags.
- Coleta paralela em várias fontes, com timeout, retry e isolamento de falhas.
- Normaliza e **deduplica** o mesmo produto entre lojas (GTIN → MPN → marca+modelo+capacidade).
- Guarda histórico de preços em SQLite (append-only) e calcula estatísticas (p10/p25/mediana/p75/p90).
- Classifica o desconto em **provavelmente real / normal / suspeito / sem evidência** usando o histórico próprio — nunca o "de/por" da loja.
- Ranqueia e destaca **melhor oferta** e **menor preço**.
- Cria alertas de preço, verifica e notifica por console ou e-mail, com **deduplicação** por faixa de preço.

### O que a Fase 1 ainda NÃO faz (de propósito)

- Não calcula **score de confiança/antifraude** — isso é a Fase 3. O `deal_score` exibido é de **oportunidade** (preço/frete/histórico), e a interface diz isso explicitamente.
- `picks.safest` e `picks.flash` vêm `null`: dependem de análise de risco e de janela de promoção.
- Não faz scraping de HTML de lojas. Novas lojas entram por **feed JSON documentado** ou API oficial.
- A fonte `fixture` é **demonstração offline**: preços fictícios, marcados como tal em toda saída.

---

## Instalação (desenvolvimento)

```bash
py -3 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"   # Windows
# source .venv/bin/activate && pip install -e ".[dev]"   # Linux/macOS
```

Ou, em qualquer sistema, como ferramenta isolada:

```bash
pipx install .
```

## Uso

```bash
dealhunter --help
dealhunter --version
dealhunter status
dealhunter db migrate
dealhunter config path
```

### Demonstração offline (sem rede, dados fictícios)

```bash
dealhunter search "Redmi Note 256GB até R$1800" --source fixture
dealhunter history redmi
```

A saída sempre avisa que os preços são de demonstração.

### Busca

```bash
# linguagem natural
dealhunter search "notebook para programação até R$ 4.000, 16 GB de RAM, SSD 512 GB"

# flags (equivalente estruturado)
dealhunter search --product "Redmi Note 14" --storage 256 --ram 8 --max-price 1800

# Mercado Livre (fonte padrão)
dealhunter search "iphone 16 128gb"

# ajustes
dealhunter search "rtx 4070" --max-price 3500 --exclude-store "Loja X" --sort price --limit 10
```

Flags principais: `--product`, `--brand`, `--category`, `--max-price`, `--min-price`,
`--storage`, `--ram`, `--condition new|used|any`, `--exclude-store`, `--source`,
`--sort best|price|reputation`, `--limit`.

### Histórico

```bash
dealhunter history "redmi note 14"        # por termo
dealhunter history prd_1a2b3c4d5e6f7890   # por ID do produto
dealhunter history off_1a2b3c4d5e6f7890 --days 30
```

### Alertas

```bash
dealhunter alerts create "Redmi Note 14 256GB" --max-price 1600
dealhunter alerts create "rtx 4070" --discount 15 --channel console
dealhunter alerts list
dealhunter alerts check            # verifica todos os ativos
dealhunter alerts check 1 --source fixture
dealhunter alerts pause 1
dealhunter alerts resume 1
dealhunter alerts delete 1
```

Regras: `--max-price` (preço final, com frete) **ou** `--discount` (percentual abaixo
da média histórica). A mesma oferta na mesma faixa de preço (R$ 50) não notifica duas vezes.

### Notificações

```bash
dealhunter notify status
dealhunter notify test
dealhunter notify test --channel console
```

E-mail usa SMTP (`smtplib`). A senha vem de `DEALHUNTER_SMTP_PASSWORD` — nunca do TOML.

### Fontes

```bash
dealhunter sources list
```

## Saída JSON

O stdout é sempre um envelope estável; logs vão para stderr.

```bash
dealhunter --json search "redmi note 14 256gb" --source fixture
```

```json
{
  "schema_version": "1.0",
  "command": "search",
  "generated_at": "2026-10-28T14:02:11+00:00",
  "query": {
    "raw": "redmi note 14 256gb ate R$1800",
    "spec": { "product": "redmi note 14", "brand": "xiaomi", "storage_gb": 256, "max_price_cents": 180000 }
  },
  "sources": [{ "id": "fixture", "status": "ok", "items": 3, "discarded": 0, "duration_ms": 0 }],
  "picks": { "best": "off_...", "cheapest": "off_...", "safest": null, "flash": null },
  "stats": { "collected": 3, "eligible": 3, "discarded": 0, "discard_reasons": {}, "duration_ms": 33 },
  "results": [
    {
      "offer_id": "off_...",
      "product_id": "prd_...",
      "title": "Smartphone Xiaomi Redmi Note 14 256GB",
      "brand": "xiaomi",
      "storage_gb": 256,
      "ram_gb": 8,
      "identity": "model",
      "store": { "name": "ImportaFacil", "domain": "demo.local" },
      "seller": { "name": "ImportaFacil", "rating": 3.9 },
      "price_cents": 149900,
      "list_price_cents": 249900,
      "shipping_cents": 4900,
      "final_price_cents": 154800,
      "currency": "BRL",
      "deal_score": 85.3,
      "discount": { "classification": "suspicious", "evidence": "desconto anunciado não corroborado: ..." },
      "history": {
        "samples": 12, "days_covered": 60, "average_cents": 174408, "median_cents": 174945,
        "min_cents": 149900, "max_cents": 197900, "position_pct": 8.3,
        "sufficient": true, "discount_vs_average_pct": 14.1
      },
      "flags": [],
      "url": "https://demo.local/importafacil/redmi-note-14-256",
      "source": "fixture",
      "collected_at": "2026-10-28T14:02:11+00:00",
      "confidence": 0.4
    }
  ],
  "warnings": ["Dados de demonstração (fonte 'fixture') incluídos: ..."]
}
```

O histograma de preços **não** é inflado por rechecagens: a mesma oferta com o mesmo preço
gera no máximo uma amostra por hora (mudança de preço é sempre registrada).

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
max_concurrency = 6

[notifications]
channels = ["console"]
# email_to = "voce@exemplo.com"
# smtp_host = "smtp.exemplo.com"
# smtp_user = "conta@exemplo.com"
# email_from = "conta@exemplo.com"

[sources]
enabled = ["mercadolivre"]      # "fixture" só para demonstração
respect_robots = true
feed_urls = []                  # feeds JSON de lojas/afiliados
```

**Segredos nunca vão no TOML** — apenas o nome da variável de ambiente ou a entrada do keyring.

### Fonte `feed` (adapter genérico)

Uma loja entra sem código novo se expuser um JSON neste formato:

```json
{
  "offers": [
    {
      "title": "Smartphone Xiaomi Redmi Note 14 256GB",
      "url": "https://loja.exemplo.com/produto/123",
      "price": "1649.90",
      "list_price": "1999.00",
      "shipping": "0",
      "currency": "BRL",
      "store": "Loja Exemplo",
      "store_domain": "loja.exemplo.com",
      "seller": "Loja Exemplo Oficial",
      "seller_rating": 4.7,
      "brand": "Xiaomi",
      "gtin": "7891234567895",
      "condition": "new",
      "availability": "in_stock"
    }
  ]
}
```

`robots.txt` é consultado e respeitado antes de acessar o feed.

---

## Como o desconto é classificado

O "de/por" da loja nunca é aceito como verdade. A ferramenta compara o preço atual com
o histórico que ela mesma coletou (mínimo de 8 amostras em 45 dias):

| Classificação | Critério |
|---|---|
| `likely_real` | preço atual no p10 do histórico e o "de" anunciado é plausível |
| `normal` | preço dentro da faixa habitual (p25–p75) |
| `suspicious` | "de" anunciado mais de 10% acima do p90 histórico (não corroborado) |
| `insufficient_evidence` | ainda não há histórico suficiente — e a saída diz isso |

Sem histórico, a resposta é **"sem evidência suficiente"**; nunca um chute.

---

## Arquitetura

Arquitetura hexagonal: `cli → application → domain ← adapters`.

```
src/dealhunter/
├─ cli/            # Typer + Rich: comandos, render, ui, wiring
├─ domain/         # modelos, value objects, portas (clock), ids
├─ application/    # casos de uso (search, alerts), DTOs, intent parser
├─ adapters/       # http (SSRF/robots), sources, storage, notify
├─ services/       # text, normalizer, matching, pricing, ranking
├─ runtime/        # config, logging, container, paths
└─ data/           # migrations SQL
```

Documento completo: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
Decisões registradas: [`docs/adr`](docs/adr).

## Testes

```bash
.venv\Scripts\python -m pytest        # suíte completa
.venv\Scripts\python -m ruff check src tests
.venv\Scripts\python -m ruff format --check src tests
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
