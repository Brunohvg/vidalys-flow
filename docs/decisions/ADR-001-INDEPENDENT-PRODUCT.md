# ADR-001 — Produto independente

Status: aceito.

## Decisão

A Vidalys Flow é um produto tecnicamente independente. Possui repositório,
projeto Django, autenticação, banco, Redis, filas, migrations e deployment
próprios.

Não existe execução conjunta, importação histórica ou dependência de runtime
com o Flowlog. O sistema anterior é somente referência temporária de regras
durante a reconstrução.
