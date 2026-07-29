# ADR-003 — Banco e migrations novos

Status: aceito.

## Decisão

PostgreSQL 17 é a fonte de verdade. O banco começa vazio e recebe apenas
migrations geradas neste repositório para models nativos.

Não são aceitos dumps, IDs, dados, migrations copiadas, compatibilidade de
tabelas, `--fake` ou operações de importação do sistema anterior.
