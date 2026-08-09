# ADR-013 — Quantidades, cancelamento, idempotência e concorrência

Status: implementado e ratificado na Fase 4.

## Contexto

Lotes parciais concorrentes podem alocar a mesma linha além do vendido.
Retries podem duplicar lotes ou transições. O cancelamento comercial também
pode ocorrer enquanto a execução física está aberta.

## Decisão

Cada `FulfillmentItem` aloca `Decimal(12,3)` de um `OrderItem`. A soma em lotes
não cancelados não pode exceder a quantidade confirmada. Serviços usam
lock pessimista em ordem determinística, `expected_version` e recibos
idempotentes por Organization, operação e chave.

Cada comando relê o Order e bloqueia avanço após cancelamento. O evento
interno sanitizado `order.cancelled` cancela lotes abertos de modo
idempotente. Lotes concluídos são preservados, pois devolução e logística
reversa não pertencem a esta fase. Orders não importa Fulfillment.

## Consequências

Cancelamento libera alocação, conclusão mantém história e nenhum mecanismo é
interpretado como estoque. Testes PostgreSQL cobrem alocação e
cancelamento concorrentes, evento repetido ou fora de ordem e conflito de
payload idempotente.

Aceito inicialmente pela aprovação humana explícita do plano e ratificado após
implementação, Review e QA/Segurança em 8 de agosto de 2026. Isso não autoriza
deploy.
