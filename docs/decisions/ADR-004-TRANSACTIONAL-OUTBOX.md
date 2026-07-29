# ADR-004 — Outbox transacional

Status: aceito.

## Decisão

Eventos assíncronos críticos são persistidos em `platform.OutboxEvent` na
mesma transação do comando de domínio. A unicidade por organização e chave
de idempotência impede duplicação lógica.

Celery seleciona eventos pendentes, registra tentativa e marca sucesso,
retry ou estado morto. Nesta fundação o publisher é interno e não executa
I/O. Publishers externos futuros passam obrigatoriamente pelo guardrail
central de efeitos externos.
