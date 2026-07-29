# Arquitetura

## Escopo da fundação

A Vidalys Flow é um monólito modular Django. A fundação possui somente:

- `core`: primitivas sem dependência de domínio;
- `users`: identidade nativa por e-mail;
- `organizations`: organizações, unidades e Membership;
- `audit`: eventos de auditoria imutáveis e sanitizados;
- `platform`: outbox, guardrails, tarefas e healthchecks.

O grafo permitido é:

```text
users         → core
organizations → core, users
audit         → core, users, organizations
platform      → core, audit, organizations
```

`core` nunca importa outro app local. Não existem runtime alternativo,
middleware de organização, hostname tenancy ou compatibilidade de tabelas.

## Execução

- PostgreSQL 17 é a única base suportada para domínio e testes.
- Redis DB 0 é o broker Celery.
- Redis DB 1 é o cache.
- Celery possui filas declaradas `default` e `integrations`; somente
  `default` tem tarefas nesta fase.
- migrations rodam em serviço de release explícito.

## Segurança multiempresa

A organização autorizada será sempre derivada de Membership validada.
Nenhum model usa organização enviada livremente como autorização. O User
não armazena papel organizacional e pode participar de várias organizações.
