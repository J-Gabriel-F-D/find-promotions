# Testes e verificação de segurança

## Como rodar

Windows (PowerShell):

```powershell
.\scripts\test.ps1 test
.\scripts\test.ps1 unit
.\scripts\test.ps1 integration
.\scripts\test.ps1 e2e
.\scripts\test.ps1 security
.\scripts\test.ps1 functional
.\scripts\test.ps1 regression
.\scripts\test.ps1 coverage
.\scripts\test.ps1 all
```

Linux/macOS (Make):

```bash
make test
make test-unit
make test-integration
make test-e2e
make test-security
make test-functional
make test-regression
make test-coverage
make test-all
```

Também é possível usar o pytest diretamente:

```bash
python -m pytest -m security
python -m pytest -m "integration or e2e"
python -m pytest tests/security
python -m pytest --cov=dealhunter --cov-report=term-missing
```

`make test-all`/`test.ps1 all` executa: formatação, lint, mypy, bandit,
detect-secrets, pip-audit e a suíte completa com cobertura. As ferramentas de
segurança são opcionais no runtime e podem ser instaladas com:

```bash
python -m pip install -e ".[dev,security,secrets]"
```

## Organização

| Diretório | Conteúdo |
|---|---|
| `tests/unit` | regras de domínio, serviços, adapters e repositório |
| `tests/integration` | servidor HTTP local, feed/robots, falha parcial, banco |
| `tests/e2e` | fluxos completos pela CLI, inclusive cenários de segurança |
| `tests/functional` | contrato de argumentos, saída, flags globais e exit codes |
| `tests/security` | SSRF, injeção, PII, segredos, abuso, canais e fontes maliciosas |
| `tests/regression` | falhas reais encontradas e corrigidas, mantidas como regressão |

Os marcadores são aplicados automaticamente pelo diretório em
`tests/conftest.py`: `security`, `integration`, `e2e`, `functional` e
`regression`.

## Política de testes sem efeitos externos

- Nenhum teste acessa sites reais, APIs de produção, SMTP, WhatsApp ou SMS.
- HTTP é simulado com `httpx.MockTransport`/`respx` ou servidor local em
  `127.0.0.1`; o bloqueio de SSRF é desativado apenas nesse servidor local.
- E-mail usa `smtplib.SMTP` mockado. Nenhuma mensagem real é enviada.
- Segredos, tokens, e-mails e telefones usados em testes são fictícios.
- Nenhum teste acessa o cofre real: `keyring` é substituído por backend falso.
- Datas e relógios são congelados quando o teste depende de janelas/idade de
  histórico.
- Privacidade cobre exportação, opt-in de contatos, esquecimento com `--yes`,
  retenção simulada e aplicada, cascata de exclusão, minimização e preservação
  da deduplicação contra spam após a retenção.
- Segredos cobrem precedência env/keyring, backend indisponível/falho, nomes
  inválidos, ausência de eco e comandos `status`/`set`/`delete`.
- Confiança cobre separação entre `score` e `analysis_confidence`, prior de fonte,
  desconto suspeito, avaliações com amostra pequena, domínio divergente, dados
  antigos, ausência de `picks.safest` sem evidência e vocabulário sem acusação.
- Avaliações individuais cobrem parsing de `reviews.items`, descarte de autor,
  sanitização de ANSI/controles/bidi, limites de tamanho, idempotência e limite
  de leitura por loja.
- Análise de reclamações cobre sentimento derivado da nota, categorias com
  evidência rastreável, texto positivo que não vira reclamação, snippet apenas
  com opt-in, confiança por cobertura e ausência de acusação de fraude.
- Segurança dos textos cobre escape de markup/HTML, remoção de quebra de
  terminal e ausência do campo de autor.
- `interactive` cobre `help`, EOF, `search`, `reviews`, `history`, `promotions`,
  comandos desconhecidos (incluindo tentativa de shell) e rejeição de
  `--json`/`--quiet`.
- `monitor` cobre `--once`, `--cycles`, intervalo, callback, quiet hours que
  cruzam a meia-noite, janela diurna desativada, cooldown por alerta, erros
  isolados, estado persistido, execuções órfãs, lock, `--json` finito, `--quiet`
  e validação de fonte desconhecida.
- Alertas inteligentes cobrem cada filtro (`min_trust`, `max_risk`,
  `require_real_discount`, `min_analysis_confidence`), rejeição de
  `insufficient_data` como risco baixo, persistência em `alert_rule`, cascata de
  exclusão, JSON da CLI e mensagem probabilística.
- Canais externos simulam Meta Cloud API e endpoint SMS com
  `httpx.MockTransport`: template, Bearer, payload, recusa de redirecionamento,
  bloqueio de HTTP/host local/IP privado/credenciais, normalização de telefone,
  ausência de eco de token/telefone e registro condicional no notifier.
- Nenhum teste usa rede real: WhatsApp e SMS são exercitados por transporte
  falso, e o lock é testado em arquivo temporário.

## CI

`.github/workflows/ci.yml` roda em `push`/`pull_request` para `main`:

- **Qualidade** (Ubuntu, Python 3.12): `ruff format --check`, `ruff check`,
  `mypy src`, `bandit -q -r src`, `detect-secrets` e `pip-audit`.
- **Testes**: matriz Ubuntu/Windows × Python 3.12/3.13/3.14, com cobertura e
  artefato `coverage.xml`. A matriz garante que o lock (`flock` no POSIX,
  `msvcrt` no Windows) e os testes de permissão sejam exercitados no SO correto.

## Cobertura atual

- 579 testes coletados, 576 aprovados e 3 ignorados (permissões POSIX e cenários
  dependentes de plataforma) em Windows/Python 3.14.5.
- Cobertura combinada: **88,81%** (limite mínimo configurado: 85%).
- `ruff format --check`, `ruff check` e `mypy src` sem erros.
- `bandit -r src`: sem achados (o jitter de retry é marcado como `nosec B311`,
  pois não é usado para criptografia).
- `detect-secrets scan src`: nenhum segredo encontrado.
- `pip-audit --skip-editable`: nenhuma vulnerabilidade conhecida. O pacote
  local `dealhunter` é ignorado por não estar publicado no PyPI.

## Limites conhecidos

A suíte cobre apenas comportamento implementado. Ainda **não** existem, e por
isso não são testados como se existissem:

- meio de pagamento e idade do domínio no score de confiança (dados não coletados);
- execução realmente contínua por horas: o teste cobre ciclos finitos; o lock e a
  persistência são exercitados, mas não há soak test de longa duração;
- entrega real de WhatsApp/SMS: depende de credenciais e aprovação de template do
  provedor e por isso é simulada;
- coleta de avaliações por scraping ou por API que não as exponha: textos
  individuais só existem quando o feed/fixture os declarar;
- resumo de avaliações por IA: a análise atual é determinística e a IA continua
  desligada por padrão.

Esses pontos permanecem registrados como risco ou funcionalidade pendente, não
como teste aprovado artificialmente.
