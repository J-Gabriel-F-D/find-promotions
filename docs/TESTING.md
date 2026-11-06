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

# Opt-in (podem gastar dinheiro/tempo); não rodam no CI padrão
DEALHUNTER_LIVE_NOTIFY=1 python -m pytest -m live tests/live
DEALHUNTER_SOAK=1 DEALHUNTER_SOAK_CYCLES=1440 python -m pytest -m soak tests/soak
```

No PowerShell, defina as variáveis com `$env:DEALHUNTER_LIVE_NOTIFY = "1"` e
`$env:DEALHUNTER_SOAK = "1"`.

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
| `tests/live` | envio real a WhatsApp/SMS — opt-in, fora do CI padrão |
| `tests/soak` | laço prolongado do monitor — opt-in, fora do CI padrão |

Os marcadores são aplicados automaticamente pelo diretório em
`tests/conftest.py`: `security`, `integration`, `e2e`, `functional`,
`regression`, `live` e `soak`.

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
  isolados, estado persistido, execuções órfãs, lock, `--json` finito, `--quiet`,
  1440 ciclos com relógio falso e validação de fonte desconhecida.
- Daemon/PID cobre `--daemon`, `--stop`, combinações inválidas, PID já em uso,
  PID órfão/reciclado (sem matar o processo), PID corrompido, dois daemons
  concorrentes e limpeza do arquivo ao encerrar. Em Windows, o teste aceita o
  PID real do interpretador quando o `python.exe` da venv atua como shim.
- Alertas inteligentes cobrem cada filtro (`min_trust`, `max_risk`,
  `require_real_discount`, `min_analysis_confidence`), rejeição de
  `insufficient_data` como risco baixo, persistência em `alert_rule`, cascata de
  exclusão, JSON da CLI e mensagem probabilística. `alerts rule show|set|clear`
  cobre substituição, limpeza, alerta inexistente, filtro vazio, risco inválido e
  aplicação da regra editada na checagem seguinte.
- Contatos por referência cobrem parsing de `env:`/`keyring:`, rejeição de
  referência malformada, resolução no notifier, mascaramento em `config show` e
  resolução apenas com `privacy export --include-contacts`. O nome da variável e
  o valor real não aparecem na saída padrão.
- Rate limit cobre limite zero, janela rolante e concorrência com 16 threads e
  conexões/instâncias distintas no mesmo banco, comprovando que o teto global não
  é ultrapassado.
- Canais externos simulam Meta Cloud API e endpoint SMS com
  `httpx.MockTransport`: template, Bearer, payload, recusa de redirecionamento,
  bloqueio de HTTP/host local/IP privado/credenciais, normalização de telefone,
  ausência de eco de token/telefone e registro condicional no notifier. O SMS
  cobre DNS pinning, IPv6, falha de DNS e recusa quando qualquer IP resolvido é
  privado.
- Permissões cobrem POSIX (`0700/0600`) e, no Windows, ACL real via `icacls`
  (sem herança e restrita ao usuário atual) para diretório e banco recém-criado.
- Nenhum teste padrão usa rede real: WhatsApp e SMS são exercitados por
  transporte falso, e o lock é testado em arquivo temporário.
- `tests/live` só roda com `DEALHUNTER_LIVE_NOTIFY=1` e credenciais oficiais
  (`DEALHUNTER_LIVE_WHATSAPP_*`, `DEALHUNTER_LIVE_SMS_*`). `tests/soak` só roda
  com `DEALHUNTER_SOAK=1`; `DEALHUNTER_SOAK_CYCLES` controla a duração simulada.
  Ambos ficam **skipped** na suíte padrão e no CI.

## CI

`.github/workflows/ci.yml` roda em `push`/`pull_request` para `main`:

- **Qualidade** (Ubuntu, Python 3.12): `ruff format --check`, `ruff check`,
  `mypy src`, `bandit -q -r src`, `detect-secrets` e `pip-audit`.
- **Testes**: matriz Ubuntu/Windows × Python 3.12/3.13/3.14, com cobertura e
  artefato `coverage.xml`. A matriz garante que o lock (`flock` no POSIX,
  `msvcrt` no Windows), a ACL Windows e os testes de permissão sejam exercitados
  no SO correto. `live` e `soak` ficam fora da execução padrão.

## Cobertura atual

- 649 testes coletados: 642 aprovados e 7 ignorados (permissões POSIX no Windows,
  live/soak opt-in) em Windows/Python 3.14.5.
- Cobertura combinada: **88,20%** (limite mínimo configurado: 85%).
- `ruff format --check`, `ruff check` e `mypy src` sem erros.
- `bandit -r src`: sem achados; `subprocess` aparece apenas nos dois pontos
  auditados (`runtime/permissions.py` e `cli/commands/monitor.py`), com `nosec
  B404` e chamadas sem shell.
- `detect-secrets scan src tests`: apenas hashes de credenciais fictícias de
  teste; nenhum segredo real.
- `pip-audit --skip-editable`: nenhuma vulnerabilidade conhecida. O pacote
  local `dealhunter` é ignorado por não estar publicado no PyPI.

## Limites conhecidos

A suíte cobre apenas comportamento implementado. Os pontos abaixo continuam
sendo riscos/limites, e não testes aprovados artificialmente:

- meio de pagamento e idade do domínio no score de confiança (dados não coletados);
- entrega real de WhatsApp/SMS: existe teste opt-in, mas ele depende de
  credenciais, consentimento e template aprovado; o CI padrão só usa transporte
  falso e não prova entrega no aparelho;
- soak: existe teste opt-in com milhares de ciclos e relógio simulado, mas o CI
  padrão não o executa; um soak de horas em produção ainda depende de operação;
- rate limit: é global entre processos que compartilham o mesmo SQLite, não entre
  máquinas/perfis distintos (cada banco tem seu próprio teto);
- contatos: referências `env:`/`keyring:` evitam PII no TOML, mas valores
  literais continuam aceitos por compatibilidade e ainda ficam no arquivo;
- ACL Windows: usa `icacls` e é best effort; se o binário não estiver disponível
  ou falhar, a CLI continua, e o teste do SO verifica o caso normal;
- coleta de avaliações por scraping ou por API que não as exponha: textos
  individuais só existem quando o feed/fixture os declarar;
- resumo de avaliações por IA: a análise atual é determinística e a IA continua
  desligada por padrão.

Esses pontos permanecem registrados como risco ou funcionalidade pendente, não
como teste aprovado artificialmente.
