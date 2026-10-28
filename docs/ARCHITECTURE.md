# Arquitetura — DealHunter

Documento de referência. Versão 1.0 · Fase 0.

---

## 1. Escopo

Aplicação **100% CLI**. Sem web, sem mobile, sem API HTTP no MVP. A CLI é apenas
apresentação; regras de negócio vivem em `domain/` e `application/` e são
reutilizáveis por qualquer interface futura.

## 2. Requisitos

**Funcionais:** busca em linguagem natural e estruturada · coleta multi-fonte
resiliente · normalização e deduplicação de produtos · preço final (produto +
frete − descontos) · histórico e estatísticas · detecção de falso desconto ·
cupons com validação · promoções com janela temporal · reputação de loja e
vendedor · análise de avaliações e reclamações · score de confiabilidade ·
ranking com 4 curadorias · monitoramento contínuo · alertas e notificações ·
`--json`/`--quiet`/`--debug`.

**Não funcionais:** multiplataforma (Windows/macOS/Linux) · local-first
(SQLite, sem Redis) · resiliência parcial · auditabilidade · segurança
(SSRF, XSS de terminal, SQLi, secrets) · LGPD · determinismo das políticas ·
custo zero de infraestrutura · IA opcional.

## 3. Camadas

```
CLI (Typer/Rich)
  └── Application (casos de uso, DTOs, orquestradores)
        └── Domain (modelos, value objects, políticas puras, portas)
              ▲
              └── Adapters (sources, http, storage, notify, ai, clock)
```

Regra de dependência: `cli → application → domain`; `adapters → domain`.
O domínio não importa nada de fora.

**Fluxo de busca**

```
Query (natural | flags)
  → IntentResolver (IA opcional | parser determinístico) → QuerySpec validado
  → CollectorRunner (fan-out async, timeout, circuit breaker, robots guard)
  → Normalizer (identidade + dedupe) → catálogo canônico
  → PriceEngine → CouponEngine → ReviewAnalyzer
  → FakeDiscountDetector → FraudAnalyzer → RankingEngine
  → Persistência → Render (rich | json | quiet)
```

## 4. Stack

| Camada | Escolha | Motivo |
|---|---|---|
| Linguagem | Python 3.12+ | Ecossistema de scraping, parsing e IA; um processo resolve scheduler |
| CLI | Typer + Rich | Painéis, tabelas, progresso; testável com `CliRunner` |
| Validação | Pydantic v2 + pydantic-settings | Contratos na fronteira; impede dado inválido circular |
| HTTP | httpx (async) | Timeouts, HTTP/2, testável com `respx` |
| Parse | selectolax / lxml | Rápido e tolerante a HTML quebrado |
| Banco | SQLite (WAL) via stdlib/SQLAlchemy | Zero ops; migração futura para Postgres |
| Logs | structlog | JSON estruturado + redação de segredos |
| Secrets | keyring (+ env) | Credential Manager / Keychain / libsecret |
| Testes | pytest, respx, hypothesis | Unit, contrato por adapter, property-based |

## 5. Banco de dados

SQLite com `journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=5000`,
`FTS5` para busca textual e `JSON1` para evidências. Dinheiro em **centavos
inteiros**; datas em ISO-8601 UTC.

Entidades previstas: `user`, `user_preferences`, `search`, `source_run`, `store`,
`seller`, `product`, `product_identifier`, `product_spec`, `offer`,
`offer_snapshot`, `coupon`, `coupon_validation`, `promotion`, `review`,
`review_summary`, `complaint`, `fraud_analysis`, `alert`, `alert_event`,
`notification`, `notification_channel`, `collector_health`, `audit_log`.

Invariantes:

* `offer_snapshot` é **append-only** — é a fonte da verdade do histórico.
* `offer` referencia `store`, `seller` e `product` (canônico).
* Todo registro coletado carrega `source`, `source_url`, `collected_at`,
  `last_verified_at` e `confidence`.
* `alert_event.dedupe_key` é `UNIQUE` — impede notificação duplicada.

Fase 0 cria apenas `schema_migration` e `audit_log` (migração `0001_init`).

## 6. Identidade de produto

Cascata, nunca por nome:

1. GTIN/EAN validado (dígito verificador) → merge imediato.
2. `marca + MPN` → merge de alta confiança.
3. Blocking por marca + família + capacidade.
4. Similaridade: `0.35·nome + 0.30·specs críticas + 0.20·numéricos + 0.15·SKU`.
5. Decisão: `≥0.92` merge · `0.75–0.92` merge só com corroboração · `<0.75` novo.

Toda decisão é registrada com evidência e pode ser desfeita (`product merge|split`).

## 7. Preço, histórico e falso desconto

`preço final = produto + frete − desconto de promoção − cupom aplicável`

Cupom não validado nunca reduz o preço "confirmado": exibimos
`final_confirmado` e `final_com_cupom_estimado` separadamente.

Classes de desconto, comparando com **nosso** histórico:

| Classe | Critério |
|---|---|
| Provavelmente real | atual ≤ p10(90d) e preço anterior alegado ≥ p75(90d) |
| Normal | atual entre p25 e p75 |
| Suspeito | anterior alegado > p90(90d) e atual ≈ mediana (±10%) |
| Sem evidência | < 8 observações ou < 45 dias de cobertura |

`claimed_previous_price` é armazenado como campo separado e explicitamente
não confiável.

## 8. Antifraude

Determinístico e explicável. Dimensões: preço (25), histórico (20), loja (20),
vendedor (15), pagamento (10), reputação (10) — pesos renormalizados apenas
sobre dimensões com dados.

Teto rígido em combinações graves (ex.: PIX-only + domínio < 90 dias + preço
anômalo → score máximo 45). Saída: `score`, `risk_band`, `dimensions`,
`signals[]` (código, peso, direção, fonte, confiança), `analysis_confidence`,
`rules_version`.

Vocabulário obrigatório: *"baixo risco identificado com base nos dados
disponíveis"*. Proibido: "loja segura", "loja fraudulenta".

## 9. Ranking

Filtros rígidos → utilidade:

```
U = 0.30·preço + 0.15·desconto real + 0.15·histórico + 0.15·confiança
  + 0.10·avaliações + 0.05·frete + 0.10·urgência − penalidade de risco
```

`preço` é relativo ao coorte do produto canônico. Curadorias: melhor geral,
menor preço final, mais confiável, relâmpago. O `score_breakdown` alimenta a
explicação "Por que recomendamos esta oferta?".

## 10. Coleta

```python
class SourceAdapter(Protocol):
    id: str
    capabilities: set[Capability]
    async def search(self, spec: QuerySpec, ctx: CollectorContext) -> SourceResult: ...
    async def fetch_offer(self, ref: OfferRef, ctx: CollectorContext) -> OfferDetail | None: ...
    async def health(self) -> HealthStatus: ...
```

Cada fonte declara em `sources.yaml`: `tos_url`, `robots_policy`, `auth`,
`rate_limit`, `enabled_by_default`, `requires_user_consent`.

Ordem obrigatória: **API oficial → feed/afiliado → HTML público permitido**.
Proibido: burlar CAPTCHA, usar credenciais de terceiros, acessar conteúdo
autenticado, ignorar ToS.

Camada HTTP compartilhada: cache condicional, rate limit por domínio, backoff
com jitter, `User-Agent` identificável, robots.txt cacheado, `Retry-After`.

Resiliência: `gather(return_exceptions=True)`, timeout por fonte, circuit
breaker persistido, resultado parcial sempre. Quebra de scraper detectada
quando ≥40% dos itens vêm sem preço.

## 11. Jobs e notificações

Scheduler asyncio in-process + tabela `job`. Sem Redis.

* `monitor` — TUI ao vivo no terminal.
* `monitor --once` — um ciclo (cron).
* `monitor --daemon` — PID file + lock exclusivo (systemd/launchd/Task Scheduler).

Notificações em **outbox**: persiste → tenta enviar → atualiza status com retry.
Canais: console, SMTP/Resend, WhatsApp Cloud API (Meta) ou Twilio, SMS Twilio.
Opt-in por canal, quiet hours no fuso do usuário, dedupe por
`hash(alert_id, offer_id, faixa_de_preço, cupom)`.

## 12. IA

| Permitido | Proibido |
|---|---|
| Interpretar linguagem natural → `QuerySpec` | Gerar preço, cupom, loja, produto, reputação |
| Resumir avaliações | Inventar avaliações |
| Classificar reclamações | Concluir fraude |
| Redigir explicação a partir do `score_breakdown` | Introduzir números fora do breakdown |

Salvaguardas: JSON Schema na saída, `temperature=0`, cache por hash, parser
determinístico como fallback, guard que rejeita números não rastreáveis.

## 13. Segurança

Entrada validada por Pydantic · URLs apenas `http(s)` com bloqueio de IP
privado/link-local/metadata e rechecagem pós-DNS (anti-SSRF) · texto raspado
tratado como não confiável (strip de ANSI/controle antes de renderizar) · SQL
parametrizado · segredos em keyring · redação em logs · permissões restritas no
banco · auditoria de mudanças de estado.

## 14. LGPD

PII mínima (e-mail/telefone só com opt-in) · retenção configurável ·
`privacy export` / `privacy forget` · consentimento registrado por canal ·
nenhum texto com PII enviado a LLM.

## 15. Observabilidade

Logs estruturados (stderr + arquivo) · `source_run` com duração, itens,
descartes e motivo · `status` com saúde dos coletores · `rules_version` por
análise · `--debug` com timeline do pipeline.

## 16. Riscos

| Risco | Mitigação |
|---|---|
| ToS/legalidade de scraping | APIs oficiais primeiro; HTML só com opt-in e registro de conformidade |
| Anti-bot / mudança de layout | Circuit breaker, detecção de degradação, contract tests |
| Custo de APIs de busca | Cache, orçamento por execução, providers plugáveis |
| Falso positivo em dedupe | Cascata com corroboração, merge auditável e reversível |
| Falso positivo antifraude | Linguagem probabilística, evidências expostas, `confidence` separada |
| Alucinação de IA | IA fora do caminho de dados críticos; schema + guard numérico |
| Notificação duplicada | Outbox + `dedupe_key` UNIQUE + cooldown |
| Dado desatualizado exibido como atual | `last_verified_at` obrigatório + rótulo explícito |
