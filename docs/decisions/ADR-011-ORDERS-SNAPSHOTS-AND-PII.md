# ADR-011 — Snapshots e dados pessoais em Orders

Status: aceito para a Fase 3.

## Decisão

Confirmação congela nome, documento opcional, um contato operacional, endereços
padrão existentes e snapshots comerciais dos itens. Objetos de contato e
endereço usam schema fechado com versão 1.

Customer mesclado e Product/Variant indisponível bloqueiam confirmação.
`OPERATOR` vê PII mascarada; audit, outbox e logs não recebem documento,
contato ou endereço.

## Consequências

Pedidos confirmados preservam o fato histórico sem depender de cadastros
mutáveis, ao custo de reter apenas o conjunto pessoal explicitamente aprovado.
