# ADR-006 — SKU por organização

Status: aceito para a Fase 2.

## Decisão

SKU pertence a ProductVariant, é opcional e normalizado para maiúsculas. Sua
unicidade é case-insensitive e limitada à Organization. O banco PostgreSQL
mantém uma constraint funcional para proteger também escritas que não passem
pelo service.

O mesmo SKU é permitido em organizações diferentes. Código de barras e
identificadores adicionais também usam constraints tenant-scoped.

## Consequências

Não existe catálogo global. Conflitos são explícitos e nunca sobrescrevem
outro produto. Nenhuma disponibilidade ou quantidade é tratada como estoque
oficial.
