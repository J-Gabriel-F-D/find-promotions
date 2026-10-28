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
| **2 — Ofertas** | cupons, promoções, ranking por promoção, avaliações | ✅ concluída |
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

### O que a Fase 2 adiciona

- **Cupons** declarados pelas fontes: percentual, valor fixo ou frete grátis, com mínimo, teto e janela de validade.
  `coupons list` mostra os cupons conhecidos; `coupons check` simula a aplicação sobre um preço.
- **Promoções** com janela temporal (`flash`, `regular`, `clearance`). O pick `flash` só é preenchido
  quando a fonte declarou uma promoção `flash` com janela **aberta**.
- **Ranking por promoção**: o `deal_score` agora pondera preço, desconto corroborado, frete, reputação,
  histórico, avaliações e urgência — e expõe cada parcela em `score_breakdown`.
- **Avaliações**: agregado publicado pela fonte (nota, quantidade e distribuição) em `reviews` e nos cards.

Limite explícito: cupom continua sendo **declaração da fonte**, não validação. Veja
[Cupons e promoções](#cupons-e-promoções-o-que-é-e-não-é-validado).

### Limites atuais (Fases 1–2)

- Não calcula **score de confiança/antifraude** — isso é a Fase 3. O `deal_score` exibido é de
  **oportunidade** (preço/desconto/frete/histórico/avaliações/urgência), e a interface diz isso.
- `picks.safest` continua `null`: depende da análise de risco da Fase 3.
- `picks.flash` só existe quando a fonte declara promoção do tipo `flash` com janela aberta;
  promoção `regular` não recebe o selo "relâmpago".
- **Nenhum cupom é validado na loja** nesta fase. `validation` é sempre `unverified` e
  `last_verified_at` fica `null`; o Mercado Livre não expõe API pública de cupons.
- Avaliações são apenas o **agregado da fonte**. Análise de sentimento/reclamações é Fase 3.
- Não faz scraping de HTML de lojas. Novas lojas entram por **feed JSON documentado** ou API oficial.
- A fonte `fixture` é **demonstração offline**: preços, cupons e promoções fictícios, marcados em toda saída.

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

### Cupons

```bash
dealhunter coupons list                     # cupons conhecidos (exclui expirados)
dealhunter coupons list --all               # inclui expirados
dealhunter coupons list --store aurora
dealhunter coupons check AURORA10 --price 1649
dealhunter coupons check AURORA10 --price 1649 --shipping 0 --store aurora
```

`coupons check` é uma **simulação local**: aplica as regras (mínimo, teto, validade, tipo) e
mostra o total estimado. O resultado é gravado em `coupon_validation` com
`method="local_rules"`; não é uma confirmação da loja.

### Promoções

```bash
dealhunter promotions                        # promoções ainda não encerradas
dealhunter promotions --expiring-in 6        # termina nas próximas 6 horas
dealhunter promotions --all --source fixture
```

Cada linha mostra tipo (`relâmpago`, `regular`, `liquidação`), janela e situação. A urgência
é só um sinal de tempo — não indica desconto real nem confiabilidade.

### Avaliações

```bash
dealhunter reviews "redmi note 14"          # por termo (usa o produto mais recente)
dealhunter reviews prd_1a2b3c4d5e6f7890     # por ID do produto
dealhunter reviews off_1a2b3c4d5e6f7890     # por ID da oferta
```

Mostra média, quantidade e distribuição por estrelas publicadas pela fonte. Sem IA e sem
texto inventado; `--json` inclui `negative_share` e a data da coleta.

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
  "schema_version": "1.1",
  "command": "search",
  "generated_at": "2026-10-28T14:02:11+00:00",
  "query": {
    "raw": "redmi note 14 256gb ate R$1800",
    "spec": { "product": "redmi note 14", "brand": "xiaomi", "storage_gb": 256, "max_price_cents": 180000 }
  },
  "sources": [{ "id": "fixture", "status": "ok", "items": 3, "discarded": 0, "duration_ms": 0 }],
  "picks": { "best": "off_...", "cheapest": "off_...", "safest": null, "flash": "off_..." },
  "stats": { "collected": 3, "eligible": 3, "discarded": 0, "discard_reasons": {}, "duration_ms": 33 },
  "results": [
    {
      "offer_id": "off_...",
      "product_id": "prd_...",
      "title": "Xiaomi Redmi Note 14 256GB 8GB RAM 5G",
      "brand": "xiaomi",
      "storage_gb": 256,
      "ram_gb": 8,
      "identity": "model",
      "store": { "name": "Loja Aurora", "domain": "loja-aurora.demo.local" },
      "seller": { "name": "Aurora Oficial", "rating": 4.8 },
      "price_cents": 164900,
      "list_price_cents": 199900,
      "shipping_cents": 0,
      "final_price_cents": 164900,
      "estimated_final_price_with_coupon_cents": 148410,
      "currency": "BRL",
      "coupon": null,
      "coupons": [
        {
          "code": "AURORA10",
          "kind": "percent",
          "value": 10,
          "benefit": "10% de desconto",
          "min_purchase_cents": 150000,
          "max_discount_cents": 20000,
          "valid_until": "2026-11-04T12:00:00+00:00",
          "state": "active",
          "validation": "unverified",
          "last_verified_at": null,
          "applicable": true,
          "reason": "aplicável (estimativa não validada)",
          "estimated_discount_cents": 16490,
          "estimated_final_price_cents": 148410,
          "estimate": true,
          "source": "fixture",
          "source_url": "https://aurora.demo.local/redmi-note-14-256",
          "collected_at": "2026-10-28T12:40:44+00:00",
          "confidence": 0.4
        }
      ],
      "best_coupon": { "code": "AURORA10", "validation": "unverified", "applicable": true,
                       "estimated_discount_cents": 16490, "estimated_final_price_cents": 148410 },
      "promotion": {
        "kind": "flash", "label": "Relâmpago Aurora", "state": "active", "urgency": 85.0,
        "remaining": "termina em 2h57", "ends_at": "2026-10-28T15:40:44+00:00",
        "source": "fixture", "confidence": 0.4
      },
      "reviews": {
        "rating": 4.7, "count": 213,
        "distribution": { "1": 2, "2": 4, "3": 9, "4": 38, "5": 160 },
        "negative_share": 0.028, "source": "fixture", "confidence": 0.4
      },
      "deal_score": 69.2,
      "score_breakdown": {
        "price": 41.2, "discount": 60.0, "shipping": 100.0, "reputation": 96.0,
        "history": 58.3, "reviews": 94.0, "urgency": 85.0, "total": 69.2
      },
      "discount": { "classification": "normal", "evidence": "preço dentro da faixa habitual (...)" },
      "flags": ["cupom_nao_validado"],
      "url": "https://aurora.demo.local/redmi-note-14-256",
      "source": "fixture",
      "collected_at": "2026-10-28T14:02:11+00:00",
      "confidence": 0.4
    }
  ],
  "warnings": ["Dados de demonstração (fonte 'fixture') incluídos: ..."]
}
```

`best_coupon` tem o mesmo formato de um item de `coupons`, resumido acima. Os campos
`estimated_final_price_with_coupon_cents` e `estimated_*` são **estimativas** e nunca
substituem `final_price_cents`, que é o preço confirmado sem cupom.

`schema_version` passou de `1.0` para `1.1` na Fase 2 de forma **aditiva**: campos novos
(`coupons`, `best_coupon`, `promotion`, `reviews`, `score_breakdown`) e `picks.flash`
preenchido quando existe promoção `flash` com janela aberta. Consumidores que ignoram campos
desconhecidos continuam funcionando.

O histograma de preços **não** é inflado por rechecagens: a mesma oferta com o mesmo preço
gera no máximo uma amostra por hora (mudança de preço é sempre registrada).

## Flags globais

| Flag | Efeito |
|---|---|
| `--json` | Saída JSON no stdout (logs continuam no stderr) |
| `--quiet`, `-q` | Apenas eventos relevantes |
| `--debug` | Log detalhado, com segredos mascarados |
| `--no-color` | Desativa cores |
| `--no-unicode` | Usa caixas e símbolos ASCII em terminais limitados |
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
      "availability": "in_stock",
      "coupons": [
        {
          "code": "BEMVINDO10",
          "kind": "percent",
          "value": 10,
          "min_purchase": "1500",
          "max_discount": "200",
          "valid_from": "2026-10-01",
          "valid_until": "2026-12-31"
        }
      ],
      "promotion": {
        "kind": "flash",
        "label": "Relâmpago da loja",
        "starts_at": "2026-10-28T12:00:00-03:00",
        "ends_at": "2026-10-28T18:00:00-03:00"
      },
      "reviews": {
        "rating": 4.6,
        "count": 213,
        "distribution": { "1": 2, "2": 4, "3": 9, "4": 38, "5": 160 }
      }
    }
  ]
}
```

Regras do que o feed pode declarar:

- `coupons[].kind`: `percent` (`value` = pontos percentuais), `fixed` (`value` = centavos) ou
  `free_shipping` (`value` = 0). `min_purchase` e `max_discount` são em reais, como `price`.
- `valid_from`/`valid_until` aceitam ISO-8601 com fuso ou `AAAA-MM-DD`; data pura em
  `valid_until` vale até o fim do dia (UTC).
- `promotion.kind`: `flash`, `regular` ou `clearance`. Sem `starts_at`/`ends_at`, a promoção
  é registrada como "sem janela". Só `flash` com janela aberta concorre ao pick relâmpago.
- `reviews` é apenas o **agregado** publicado pela loja; a ferramenta não inventa texto,
  nem deriva sentimento a partir disso.
- Campos desconhecidos, cupons inválidos ou avaliações fora de 0–5 são ignorados sem
  derrubar a coleta.

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

## Cupons e promoções: o que é (e não é) validado

Um cupom coletado é uma **declaração da fonte**, não um fato confirmado. Por isso:

| Campo | Significado |
|---|---|
| `validation` | `unverified` na Fase 2 — nenhuma confirmação junto à loja é feita |
| `last_verified_at` | `null` enquanto não houver confirmação da loja |
| `estimate` | sempre `true` nos cálculos locais |
| `final_price_cents` | preço confirmado **sem** cupom |
| `estimated_final_price_with_coupon_cents` | cenário com cupom aplicado, **não confirmado** |

Situação do cupom: `active` (vigente), `scheduled` (ainda não começou), `expired`
(fora da janela) ou `unknown` (fonte não declarou janela). A simulação também rejeita
mínimo de compra não atingido, cupom inválido e frete grátis quando o frete não é conhecido.

`coupons check` grava a tentativa em `coupon_validation` com `method="local_rules"`.
Isso é **auditoria do que calculamos**, não validação na loja. O Mercado Livre não
oferece API pública de cupons; na Fase 2 cupons vêm apenas de feeds/fixture.

Promoções podem ter janela declarada (estado `active`/`scheduled`/`expired`) ou vir
sem janela (`unknown`). A **urgência** usada no ranking é apenas tempo restante
(0–100); ela não afirma que o desconto é real nem que a loja é confiável.

### Como o `deal_score` é composto

| Dimensão | Peso | Observação |
|---|---|---|
| Preço | 25% | posição no coorte da busca |
| Desconto corroborado | 20% | `suspicious` zera a dimensão |
| Reputação | 20% | vendedor ou loja |
| Histórico | 15% | posição na série própria |
| Frete | 10% | frete grátis/desconhecido |
| Avaliações | 5% | nota da fonte, encolhida com poucas amostras |
| Urgência | 5% | só com janela aberta |

As parcelas aparecem em `score_breakdown`. O número continua sendo **oportunidade**,
não confiança.

---

## Arquitetura

Arquitetura hexagonal: `cli → application → domain ← adapters`.

```
src/dealhunter/
├─ cli/            # Typer + Rich: comandos, render, ui, wiring
├─ domain/         # modelos, value objects, portas (clock), ids
├─ application/    # casos de uso (search, alerts, coupons, promotions, reviews), DTOs, intent
├─ adapters/       # http (SSRF/robots), sources, storage, notify
├─ services/       # text, normalizer, matching, pricing, coupons, promotions, ranking
├─ runtime/        # config, logging, container, paths
└─ data/           # migrations SQL
```

Documento completo: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
Decisões registradas: [`docs/adr`](docs/adr).

## Testes

```bash
.venv\Scripts\python -m pytest        # suíte completa
.venv\Scripts\python -m pytest -m security
.venv\Scripts\python -m pytest --cov=dealhunter --cov-report=term-missing
.venv\Scripts\python -m ruff check src tests
.venv\Scripts\python -m ruff format --check src tests
.venv\Scripts\python -m mypy src
```

Atalhos reproduzíveis: `.\scripts\test.ps1 all` no Windows e `make test-all`
no Linux/macOS. A matriz de testes, a política de mocks e os limites conhecidos
estão em [`docs/TESTING.md`](docs/TESTING.md).

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
