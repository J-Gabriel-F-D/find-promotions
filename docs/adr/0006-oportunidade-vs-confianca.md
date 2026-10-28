# ADR 0006 — `deal_score` de oportunidade ≠ score de confiança

* Status: aceito
* Data: 2026-10-28

## Contexto

A visão do produto pede duas respostas distintas: **onde está o melhor preço
agora** e **posso confiar nessa oferta?**. A segunda depende de sinais que ainda
não são coletados na Fase 1 (histórico de preço longo, reputação agregada de
reclamações, padrões de fraude, verificação de loja). Exibir um único número
chamado "score" misturaria as duas perguntas e daria à segunda uma precisão que
os dados não sustentam — exatamente o que o produto promete não fazer.

## Decisão

1. O número exibido na Fase 1 chama-se **oportunidade** (`deal_score`) e é
   calculado apenas com preço final, frete e posição no histórico.
2. Todo texto que o apresenta diz explicitamente: *"preço/frete/histórico; não é
   score de confiança"*.
3. `picks.safest` e `picks.flash` ficam `null` até existirem os dados que os
   justificam (Fase 2/3). Um `null` honesto é melhor que um palpite rotulado.
4. Quando a análise antifraude existir (Fase 3), ela virá em campos separados
   (`trust_score`, `analysis_confidence`, `evidence[]`) e com linguagem
   probabilística — nunca "esta loja é fraude" ou "é segura".

## Consequências

* **Positivas:** a saída não superestima o que a ferramenta sabe; o contrato JSON
  já reserva o espaço dos campos de confiança sem preenchê-los com ruído.
* **Negativas:** a experiência parece "incompleta" na Fase 1 — mitigado pelo
  README, pela tabela de status e pela própria interface, que rotula cada
  número com o que ele significa.
