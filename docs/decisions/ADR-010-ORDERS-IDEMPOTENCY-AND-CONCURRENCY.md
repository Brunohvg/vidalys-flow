# ADR-010 — Idempotência e concorrência em Orders

Status: aceito para a Fase 3.

## Decisão

Cada comando mutável cria `OrderCommandReceipt`, único por organização,
operação e chave. O recibo guarda somente hash canônico, IDs e versão
resultante. Repetição com payload diferente é conflito.

Mutações bloqueiam o Order e validam `expected_version`. A numeração bloqueia
`OrderNumberSequence`; a criação concorrente da primeira sequência é tratada
por savepoint, constraint OneToOne e releitura com lock.

## Consequências

Retries não duplicam pedidos, transições, audit ou outbox. Conflitos de edição
ficam visíveis em vez de sobrescrever silenciosamente outro usuário.
