# Arquitetura — DealHunter

Documento de referência. Versão 1.2 · Fase 2.

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
CLI (Typer/Rich)  +  GUI opcional (Tkinter)
  └── Application (casos de uso, DTOs, orquestradores)
        └── Domain (modelos, value objects, políticas puras, portas)
              ▲
              └── Adapters (sources, http, storage, notify, ai, clock)
```

Regra de dependência: `cli → application → domain`; `adapters → domain`.
A GUI opcional também só depende de `application`/`cli.wiring`, nunca de regra
de negócio própria.
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
| Secrets | env > keyring opcional | Variáveis de ambiente primeiro; cofre do SO via extra `[secrets]` |
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
A Fase 4 acrescenta `monitor_run`, `monitor_state` e `alert_rule` (migração
`0006_fase4`); nenhuma coluna de `alert` é alterada.

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
`final_confirmado` (`final_price_cents` no JSON) e `final_com_cupom_estimado`
(`estimated_final_price_with_coupon_cents`) separadamente.

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

Determinístico e explicável, implementado em `services/trust.py`. Dimensões e
pesos máximos: preço (25), histórico (15), loja/procedência (15), vendedor (15),
reputação/avaliações (10), frescor (10) e pagamento (10). Dimensões sem dado
não entram no numerador; o denominador continua completo, então ausência de
dado reduz `analysis_confidence` em vez de inflar o score.

`score` vai de 0 a 100 (maior = mais sinais favoráveis disponíveis) e
`analysis_confidence` vai de 0 a 1 (cobertura de evidência). São campos
separados de propósito: score alto com cobertura baixa não vira recomendação.
Saída: `score`, `risk_band`, `dimensions`, `signals[]` (código, direção, peso,
fonte, confiança e evidência), `analysis_confidence`, `limitations`,
`rules_version` e `disclaimer`.

Meio de pagamento e idade do domínio **não são coletados** nesta fase, portanto
não há teto rígido baseado neles. A limitação aparece em `limitations`. O
vocabulário obrigatório é probabilístico: *"baixo risco identificado com base
nos dados disponíveis"*. Proibido: "loja segura", "loja fraudulenta".

### 8.1 Avaliações e reclamações

Textos individuais só entram por **feed JSON documentado** ou `fixture`; não há
scraping de páginas de avaliação. O agregado continua em `review_summary` e as
linhas individuais em `review_text` (migração `0005_reviews`), com cascata a
partir do produto/agregado.

Princípios:

- **autor não é armazenado** (minimização de PII); só nota, título, corpo, data
  declarada, fonte, URL, coleta e confiança;
- o corpo é sanitizado (ANSI, controles C0/C1, bidi) e limitado antes de ser
  persistido ou renderizado; a renderização também faz `escape` de markup;
- **sentimento deriva da nota** (`4–5` positivo, `3` neutro, `1–2` negativo),
  sem modelo de linguagem;
- **reclamações são menções** encontradas no texto, agrupadas por categoria, com
  `review_id`, termos casados e trecho apenas com `--include-text`;
- `analysis_confidence` mede cobertura da amostra (`with_text / sample_size` e
  tamanho), não probabilidade de fraude;
- sem texto publicado, a saída declara que a análise não pôde ser feita;
- `rules_version = "reviews-v1"` e `disclaimer` acompanham toda análise.

Análise implementada em `services/reviews.py`, exposta por
`application/use_cases/reviews.py` e pelo comando `reviews`
(`--include-text`, `--limit`). Textos ficam fora do JSON por padrão.

## 9. Ranking

Filtros rígidos → utilidade:

```
U = 0.30·preço + 0.15·desconto real + 0.15·histórico + 0.15·confiança
  + 0.10·avaliações + 0.05·frete + 0.10·urgência − penalidade de risco
```

A fórmula acima é a implementada. A penalidade é explícita e aparece em
`score_breakdown.risk_penalty`: desconto `suspicious` (+5), cobertura de
confiança abaixo do mínimo (+2) e faixa `elevated` (até +10). `desconto` usa a
classificação da seção 7: `suspicious` zera a dimensão, `insufficient_evidence`
fica no neutro (50).

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

Scheduler asyncio in-process. Sem Redis, sem fila externa.

* `monitor --once` — um ciclo (cron/Task Scheduler/systemd timer).
* `monitor --cycles N --interval S` — execução finita, útil para batches.
* `monitor` — ciclos contínuos até interrupção, com lock exclusivo mantido aberto.
* `monitor --daemon` — reexecuta a própria CLI como processo destacado e retorna;
  `monitor --stop` encerra via PID file, mas só depois de confirmar que o lock do
  monitor está ocupado.

O PID file (`monitor.pid`) é auxiliar e privado. Um PID existente não prova que o
processo é o monitor: `--stop` valida o lock antes de enviar sinal, reduzindo o risco
de matar um PID reciclado. PIDs ausentes/corrompidos são removidos.

O monitor reutiliza `AlertService.check`; não duplica regras, dedupe nem outbox.
`monitor_run` registra cada sessão e `monitor_state` guarda o último estado.
Quiet hours usam `general.timezone`; cooldown é por alerta e consulta
`alert_event` desde o corte configurado.

Notificações em **outbox**: persiste → tenta enviar → atualiza status com retry.
Canais: console, SMTP, **WhatsApp Cloud API (Meta, template obrigatório)** e
**SMS por endpoint HTTPS oficial configurável**. Opt-in por canal, quiet hours no
fuso do usuário, dedupe por `hash(alert_id, offer_id, faixa_de_preço, cupom)`.
WhatsApp e SMS ficam desligados sem configuração completa; tokens vêm do ambiente
ou keyring, nunca do TOML.

O teto `notifications.max_per_hour` é aplicado por `reserve_notification` com
`BEGIN IMMEDIATE`: contar e inserir acontecem na mesma transação, então o limite é
global entre conexões, instâncias e processos que compartilham o banco. Se o teto
já foi atingido, o canal registra a falha sem enviar.

Contatos (`email_to`, `email_from`, `smtp_user`, `whatsapp_phone`, `sms_to`,
`sms_from`) aceitam referências `env:NOME`/`keyring:NOME`. A referência é resolvida
no composition root do notifier; `config show` e exportações sem opt-in exibem
`env:***`/`keyring:***`, nunca o nome ou o valor.

O adapter SMS resolve o DNS, recusa se **qualquer** endereço for privado/loopback/
link-local/reservado e fixa o IP validado na URL da conexão, mantendo `Host` e
`sni_hostname` originais. `trust_env=False` impede que um proxy ambiente troque o
destino. Redirecionamentos não são seguidos.

## 12. IA

| Permitido | Proibido |
|---|---|
| Interpretar linguagem natural → `QuerySpec` | Gerar preço, cupom, loja, produto, reputação |
| Resumir avaliações | Inventar avaliações |
| Classificar reclamações | Concluir fraude |
| Redigir explicação a partir do `score_breakdown` | Introduzir números fora do breakdown |

Salvaguardas: JSON Schema na saída, `temperature=0`, cache por hash, parser
determinístico como fallback, guard que rejeita números não rastreáveis.

Na Fase 3 a análise de avaliações/reclamações é **100% determinística** e não
usa IA. A IA continua opcional, desligada por padrão e sem acesso a textos de
avaliação nesta fase. Qualquer resumo futuro por LLM deve enviar apenas dados
já sanitizados, manter o fallback determinístico e nunca concluir fraude.

## 13. Segurança

Entrada validada por Pydantic · URLs apenas `http(s)` com bloqueio de IP
privado/link-local/metadata e rechecagem pós-DNS (anti-SSRF) · texto raspado
tratado como não confiável (strip de ANSI/controle/bidi antes de persistir e de
renderizar, mais `escape` de markup) · SQL parametrizado · segredos em
variáveis de ambiente ou keyring opcional (env tem precedência) · redação em
logs · permissões restritas no banco · auditoria de mudanças de estado ·
`interactive` sem shell escape/`eval`.

Permissões locais: POSIX usa `0700` em diretórios e `0600` em arquivos; Windows usa
`icacls` com `/inheritance:r /grant:r <usuário>:(OI)(CI)F` (diretório) ou
`<usuário>:F` (arquivo). A restrição é best effort: falhas não derrubam a CLI, mas
são cobertas por testes no SO correspondente. `subprocess` é permitido apenas em
`runtime/permissions.py` (icacls) e `cli/commands/monitor.py` (spawn do daemon),
sempre com lista fixa de argumentos, sem shell e sem interpolar entrada do usuário.

## 14. LGPD

PII mínima (e-mail/telefone só com opt-in) · retenção configurável ·
`privacy export` / `privacy forget` / `privacy retention` · consentimento por
canal na configuração · nenhum texto com PII enviado a LLM · textos de avaliação
são conteúdo público da fonte e não entram no `forget`; o autor não é
armazenado.

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

## 17. Status de implementação

### Fase 0 — concluída

Configuração (TOML + env + flags), logging estruturado com redação de segredos,
SQLite com migrações versionadas, container/DI, `status`, `db`, `config`,
envelope `--json`, exit codes.

### Fase 1 — concluída

| Área | Implementado |
|---|---|
| Coleta | `MercadoLivreAdapter` (API oficial `/sites/MLB/search`), `FeedAdapter` (JSON genérico + robots.txt), `FixtureAdapter` (demo offline marcada) |
| Rede | `HttpClient` com SSRF guard (IP privado/loopback/link-local, esquema, credenciais), retry com backoff e `Retry-After`, timeout |
| Normalização | marca, categoria, capacidades, GTIN, identidade em cascata (GTIN → MPN → marca+família+capacidade → título isolado) |
| Histórico | `offer_snapshot` append-only, `price_samples` por produto/oferta, percentis, `sufficient_history` (8 amostras/45 dias) |
| Desconto | `likely_real` / `normal` / `suspicious` / `insufficient_evidence`, sempre com evidência textual |
| Ranking | `deal_score` de oportunidade (preço/desconto/histórico/confiança), picks `best`/`cheapest`/`safest`/`flash`; `trust` separado |
| Alertas | regras `max-price`/`discount`, canais console/SMTP, dedupe por faixa de R$ 50, pausar/retomar/remover |
| CLI | `search`, `history`, `alerts`, `notify`, `privacy`, `secrets`, `sources`, além de `status`/`db`/`config` |

Desvios conscientes em relação ao desenho original:

1. **Sem scraping de HTML.** Nenhuma loja específica é raspada na Fase 1; novas
   lojas entram por API oficial ou feed JSON documentado (decisão de
   conformidade, ver seção 16).
2. **`deal_score` não é confiança.** Ver ADR 0006; a confiança fica em `trust`,
   com score e `analysis_confidence` próprios.
3. **Dedupe conservador.** Sem evidência forte, produtos não são fundidos
   (ADR 0005).
4. **IA permanece desligada por padrão e sem uso na Fase 1.** O parser de intenção
   é 100% determinístico; o caminho de IA fica para a Fase 3 (resumo de
   avaliações/reclamações), com schema + guard numérico já previstos.
5. **`interactive` adiado para a Fase 3 e `monitor` para a Fase 4**, conforme
   roadmap. Ambos foram entregues nas fases correspondentes.

### Fase 2 — concluída

| Área | Implementado |
|---|---|
| Cupons | `coupon` + `coupon_validation`; tipos percentual/valor fixo/frete grátis; mínimo, teto e janela; `coupons list`/`check` |
| Promoções | `promotion` com janela e tipo (`flash`/`regular`/`clearance`); `promotions` com filtros de fonte e expiração |
| Ranking | `deal_score` com preço, desconto corroborado, frete, confiança, histórico, avaliações e urgência; `score_breakdown`; `picks.flash` |
| Avaliações | `review_summary` (agregado da fonte) e comando `reviews`; distribuição por estrelas |
| CLI/JSON | `coupons`, `promotions`, `reviews`; envelope `schema_version` 1.1 (aditivo) |

Desvios conscientes da Fase 2:

1. **Cupom não é validado na loja.** `validation` é sempre `unverified` e
   `last_verified_at` permanece nulo; `coupons check` executa regras locais e
   registra `method="local_rules"` em `coupon_validation`. O Mercado Livre não
   expõe API pública de cupons, então cupons vêm de feed/fixture.
2. **`review` individual não é coletada.** A Fase 2 guarda apenas o agregado
   publicado (`review_summary`). Texto de avaliação e reclamações exigem a
   Fase 3 e as salvaguardas de IA (seção 12).
3. **Identidade de estado atual.** `coupon` tem identidade `(loja, código)` e
   `promotion` tem identidade `(oferta, tipo)`: uma nova coleta atualiza a janela
   em vez de duplicar linhas. O histórico de preços continua em
   `offer_snapshot`, que é append-only.
4. **Fixture usa subdomínios `*.demo.local`.** `Store.id` deriva do domínio;
   compartilhar `demo.local` faria todas as lojas demo colapsarem em uma só.

### Fase 3 — concluída

| Área | Implementado |
|---|---|
| Confiança | `TrustAssessment` com `score` 0–100, `analysis_confidence` 0–1, `risk_band`, dimensões, sinais, limitações e `rules_version` |
| Sinais | procedência da fonte/loja, domínio/HTTPS, vendedor, avaliações agregadas, desconto, histórico e frescor |
| Ranking | `picks.safest` quando há score ≥ 50 e cobertura ≥ 0,30; caso contrário `null` |
| Avaliações | `review_text` (migração `0005_reviews`), parsing de `reviews.items` no feed, textos demo marcados, sanitização e `--include-text`/`--limit` |
| Reclamações | análise determinística em `services/reviews.py`: sentimento pela nota, menções por categoria, evidências rastreáveis, `analysis_confidence` e `disclaimer` |
| Interativo | `interactive` com `search`/`reviews`/`history`/`promotions`/`help`/`sair`, sem shell escape |
| Explicabilidade | evidência textual por sinal, `disclaimer` obrigatório e JSON aditivo dentro de cada oferta/análise |
| Testes | `test_trust.py`, `test_reviews.py`, `test_review_text_safety.py`, `test_cli_interactive.py`, e2e de guardrails e cenários de injeção/ANSI |

Limitações mantidas: meio de pagamento e idade do domínio não são coletados;
não há teto rígido baseado neles. Avaliações individuais dependem de feed/fixture
e a análise não prova fraude nem representa toda a base de clientes.

### Fase 4 — concluída

| Área | Implementado |
|---|---|
| Monitor | `MonitorService` com ciclos, `--once`, `--cycles`, intervalo, quiet hours, cooldown por alerta, callback de ciclo e erros isolados |
| Estado | migração `0006_fase4`: `monitor_run`, `monitor_state`; `monitor --json` expõe `previous_run`, ciclos e totais |
| Daemon/PID | `monitor --daemon/--stop`, `runtime/process.py` (PID atômico/privado), spawn sem shell e parada só com lock ocupado |
| Lock | `adapters/storage/lock.py` com `flock` (POSIX) / `msvcrt.locking` (Windows), não bloqueante, liberado em `finally` |
| Alertas inteligentes | `alert_rule` opcional: `min_trust`, `max_risk`, `require_real_discount`, `min_analysis_confidence`; editáveis com `alerts rule show/set/clear` |
| WhatsApp | `adapters/notify/whatsapp.py` pela Meta Cloud API, template obrigatório, `follow_redirects=False`, token nunca ecoado |
| SMS | `adapters/notify/sms.py` por endpoint HTTPS oficial, DNS pinning com validação de todos os IPs, `Host`/SNI originais, `trust_env=False` |
| Rate limit | `reserve_notification` com `BEGIN IMMEDIATE`; limite global entre processos, não apenas por instância |
| Contatos | referências `env:`/`keyring:` resolvidas no notifier; `config show`/exportação padrão mascaram origem e nome |
| Notificações | `notify status` lista console/e-mail/WhatsApp/SMS; canais só entram com configuração completa |
| Permissões | POSIX `0700/0600`; Windows ACL via `icacls`, verificada nos testes do Windows |
| CLI | `monitor` com `--json`/`--quiet`, validação de fonte, exit code 1 para lock/erro e 2 para uso inválido |
| Testes opt-in | `tests/live` (WhatsApp/SMS reais) e `tests/soak` (milhares de ciclos), fora do CI padrão |
| CI | GitHub Actions em Ubuntu/Windows × Python 3.12/3.13/3.14 + lint, mypy, bandit, detect-secrets e pip-audit |

Decisões e limites da Fase 4:

1. **`monitor` não reimplementa alertas.** Ele orquestra `AlertService.check` e
   apenas pula alertas em cooldown; regras, dedupe e outbox continuam em um só lugar.
2. **Cooldown é por alerta, não por oferta.** Dois alertas distintos podem
   notificar a mesma oferta; o dedupe por faixa de preço continua evitando repetição
   do mesmo alerta.
3. **`insufficient_data` não é risco baixo.** `--max-risk` só aceita uma faixa
   observável; sem dados, o alerta não casa com a regra conservadora.
4. **Canais externos são opt-in e oficiais.** WhatsApp exige template aprovado;
   SMS exige endpoint HTTPS de provedor oficial. Não há automação de app, modem
   ou gateway não documentado.
5. **`--json` exige execução finita.** `--once` ou `--cycles`; sem isso, não há
   documento final para o envelope.
6. **CI usa matriz real.** Linux valida permissões POSIX e o lock `flock`;
   Windows valida `msvcrt`, ACL via `icacls`, caminhos e `tzdata`.
7. **Daemon não é serviço.** `--daemon`/PID file resolvem execução permanente no
   mesmo usuário, mas não substituem supervisor de reboot (systemd/Task Scheduler).
8. **Rate limit é local ao banco.** A transação atômica serializa processos que
   compartilham o mesmo SQLite; máquinas/perfis distintos têm tetos independentes.
9. **Entrega real e soak são opt-in.** `DEALHUNTER_LIVE_NOTIFY=1` e
   `DEALHUNTER_SOAK=1` habilitam testes que gastam dinheiro/tempo e por isso não
   entram no CI padrão.

### Interface gráfica opcional (Tkinter)

`dealhunter ui` abre uma janela desktop com abas de busca, histórico, avaliações,
alertas e monitor. Decisões:

1. **Tkinter é da biblioteca padrão.** Nenhuma dependência nova entra no produto;
   a UI é opcional e a CLI continua sendo o caminho de automação.
2. **A janela não tem regra de negócio.** `gui/controller.py` valida entrada e
   chama `run_search`, `run_history`, `run_reviews`, `run_alerts_check`,
   `run_monitor`, `create_alert` e o repositório, os mesmos usados pela CLI.
   `gui/format.py` só formata fatos devolvidos pelos casos de uso.
3. **Import preguiçoso.** O comando `ui` importa `gui.app` apenas na execução;
   `--help` funciona sem Tkinter/display. Falta de Tkinter ou display vira
   mensagem amigável e exit code 1.
4. **Thread + fila.** Operações de rede rodam em uma thread de trabalho e
   devolvem o resultado à thread principal por `queue.Queue`, mantendo o Tkinter
   responsivo e sem chamadas de UI fora da thread principal.
5. **Monitor contínuo continua na CLI.** A janela executa um ciclo (`--once`) e
   exibe a última execução registrada; `--daemon`/`--stop` seguem no terminal.
6. **Testes headless.** A lógica é testada sem importar Tkinter e o contrato do
   comando é testado sem abrir janela, inclusive em ambientes sem display.
7. **Confiança não vira veredito.** A UI mostra `score`, `analysis_confidence` e
   a faixa observável separadamente; nada é apresentado como acusação de fraude.

### Dados de demonstração

A fonte `fixture` existe para testes e demonstração offline. Ela nunca é
habilitada por padrão, usa domínios `*.demo.local`, confiança ≤ 0,4 e injeta um
aviso obrigatório em toda saída (inclusive no JSON).
