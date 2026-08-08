# ADR-013 — Quantidades, cancelamento, idempotência e concorrência

Status: aceito para implementação na Fase 4.

## Contexto

Lotes parciais concorrentes podem alocar a mesma linha além do vendido.
Retries podem duplicar lotes ou transições. O cancelamento comercial também
pode ocorrer enquanto a execução física está aberta.

## Decisão proposta

Cada `FulfillmentItem` aloca `Decimal(12,3)` de um `OrderItem`. A soma em lotes
não cancelados não poderá exceder a quantidade confirmada. Serviços usarão
lock pessimista em ordem determinística, `expected_version` e recibos
idempotentes por Organization, operação e chave.

Cada comando relerá o Order e bloqueará avanço após cancelamento. O evento
interno sanitizado `order.cancelled` cancelará lotes abertos de modo
idempotente. Lotes concluídos serão preservados, pois devolução e logística
reversa não pertencem a esta fase. Orders não importará Fulfillment.

## Consequências

Cancelamento libera alocação, conclusão mantém história e nenhum mecanismo é
interpretado como estoque. Testes PostgreSQL deverão cobrir alocação e
cancelamento concorrentes, evento repetido ou fora de ordem e conflito de
payload idempotente.

Aceito pela aprovação humana explícita do plano em 8 de agosto de 2026. Isso
não aprova implementação, merge ou deploy.
