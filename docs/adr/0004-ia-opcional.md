# ADR 0004 — IA opcional, fora do caminho dos dados críticos

* Status: aceito
* Data: 2026-10-28

## Contexto

LLMs são úteis para interpretar linguagem natural e resumir texto, mas não são
fontes de verdade. Preço, disponibilidade, cupom e reputação precisam ser
rastreáveis e reprodutíveis.

## Decisão

1. A IA é **opcional**. Sem chave configurada (ou com `--no-ai`), a
   interpretação usa um parser determinístico por regex + léxico.
2. A IA nunca gera preço, cupom, loja, produto, avaliação ou dado de reputação.
3. Toda saída de IA é validada por JSON Schema.
4. Um guard pós-geração rejeita qualquer número que não exista no dicionário de
   evidências; nesse caso a saída cai para um template determinístico.
5. `temperature = 0` e cache por hash da entrada.
6. Dados pessoais são removidos antes de qualquer prompt.

## Consequências

* **Positivas:** o produto funciona (e é testável) sem custo de API; nenhuma
  decisão de risco depende de LLM; respostas reproduzíveis.
* **Negativas:** o parser determinístico cobre menos variações de linguagem que
  um LLM — aceitável no MVP, e o fallback é explícito para o usuário.
