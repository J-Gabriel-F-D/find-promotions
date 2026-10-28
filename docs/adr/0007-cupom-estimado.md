# ADR 0007 — Cupom declarado ≠ cupom validado

* Status: aceito
* Data: 2026-10-28

## Contexto

A Fase 2 passa a exibir cupons, mas as fontes disponíveis não permitem confirmar
vigência junto à loja: o Mercado Livre não oferece API pública de cupons e não
fazemos scraping de HTML. Um feed pode declarar qualquer código, valor ou prazo.
Se o cupom entrasse no preço "confirmado", a ferramenta repetiria o erro que
promete evitar: apresentar como fato algo que ninguém verificou.

## Decisão

1. Cupom coletado é uma **declaração da fonte**. `validation` é sempre
   `unverified` e `last_verified_at` permanece `null` até uma confirmação real
   junto à loja (que a Fase 2 não realiza).
2. O preço confirmado (`final_price_cents`) **nunca** inclui cupom. O cenário com
   cupom aparece à parte, com `estimate: true` e
   `estimated_final_price_with_coupon_cents`.
3. `coupons check` aplica apenas **regras locais** (tipo, mínimo, teto, janela,
   frete conhecido) e registra cada tentativa em `coupon_validation` com
   `method="local_rules"`. Isso é auditoria do cálculo, não validação na loja.
4. A interface sempre diz "não validado na loja"; `--json` inclui a mesma
   advertência em `warnings`.
5. Promoção também é declarada: sem janela, o estado é `unknown` e ela não
   concorre ao pick `flash`. Só promoções do tipo `flash` com janela aberta
   podem receber o selo "relâmpago". Urgência mede apenas tempo restante — não
   desconto real nem confiabilidade.

## Consequências

* **Positivas:** o usuário vê o benefício potencial sem que o preço confirmado
  seja contaminado; a origem e a data de cada cupom ficam auditáveis.
* **Negativas:** a experiência é mais conservadora que a de sites de cupom;
  cupons expirados ou inválidos só são detectados pelas regras locais. Isso é
  aceitável porque o custo de um falso "cupom válido" é maior que o de um
  "não validado".
