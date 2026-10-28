# ADR 0005 — Deduplicação por identidade forte (nunca por nome parecido)

* Status: aceito
* Data: 2026-10-28

## Contexto

O mesmo produto aparece em várias lojas com títulos diferentes
("Xiaomi Redmi Note 14 256GB 8GB RAM 5G", "Smartphone Xiaomi Redmi Note 14 256GB").
Para comparar preços é preciso agrupá-los. Ao mesmo tempo, agrupar errado é pior
do que não agrupar: fundir "IdeaPad 3 8GB" com "IdeaPad 3 16GB" inventaria uma
comparação que não existe e poderia destacar uma oferta como "a mais barata"
quando é outro produto.

## Decisão

A identidade é resolvida em cascata, da evidência mais forte para a mais fraca:

1. **GTIN/EAN** (8–14 dígitos) — identificador global do fabricante.
2. **MPN + marca** — código de modelo do fabricante.
3. **Marca + família do modelo + armazenamento (+ RAM)** — família extraída de
   tokens úteis do título, parando no primeiro token de componente (CPU), para
   que "IdeaPad 3 Ryzen 5" e "IdeaPad 3" caiam na mesma família.
4. **Título normalizado** — usado apenas como *fallback*, e nesse caso o produto
   **não** é fundido com nenhum outro (a chave inclui o hash do título).

O `product_id` é determinístico (SHA-256 truncado da chave), o que torna a coleta
idempotente: rodar a mesma busca duas vezes não duplica produto, loja ou oferta.

## Consequências

* **Positivas:** comparação de preços confiável entre lojas quando há evidência;
  IDs estáveis entre execuções; nenhuma heurística de similaridade "esperta"
  capaz de fundir produtos diferentes.
* **Negativas:** quando o título omite capacidade, o produto pode não ser fundido
  (preferimos isso a fundir errado). Uma etapa de *blocking + similaridade
  ponderada* com revisão pode ser adicionada na Fase 2, sempre com a mesma regra:
  similaridade nunca decide sozinha.
