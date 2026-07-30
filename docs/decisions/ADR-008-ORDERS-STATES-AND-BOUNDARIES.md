# ADR-008 — Estados e fronteiras de Orders

Status: aceito para a Fase 3.

## Decisão

Orders usa apenas `draft`, `confirmed` e `cancelled`. `completed`, `returned`,
pagamento, fulfillment, mensagens, integrações e estados de provider não são
persistidos no enum do pedido.

`OrderStatusHistory` é o livro imutável das transições canônicas; AuditEvent
continua sendo a trilha transversal. Cancelamento exige manager tier e motivo,
mas o texto do motivo não sai no audit ou outbox.

## Consequências

A Fase 3 não consegue concluir nem devolver pedidos. Esses comportamentos
serão adicionados por contratos explícitos quando seus domínios existirem.
