# Arquitetura

## Escopo atual

A Vidalys Flow é um monólito modular Django. A fundação possui somente:

- `core`: primitivas sem dependência de domínio;
- `users`: identidade nativa por e-mail;
- `organizations`: organizações, unidades e Membership;
- `audit`: eventos de auditoria imutáveis e sanitizados;
- `platform`: outbox, guardrails, tarefas e healthchecks.
- `customers`: identidade, contatos, endereços, notas e merge;
- `products`: catálogo operacional, variantes e identificadores.

O grafo permitido é:

```text
users         → core
organizations → core, users
audit         → core, users, organizations
platform      → core, audit, organizations
customers     → core, users, organizations, audit, platform
products      → core, users, organizations, audit, platform
```

`core` nunca importa outro app local. Não existem runtime alternativo,
middleware de organização, hostname tenancy ou compatibilidade de tabelas.
Customers e Products não importam um ao outro.

## Execução

- PostgreSQL 17 é a única base suportada para domínio e testes.
- Redis DB 0 é o broker Celery.
- Redis DB 1 é o cache.
- Celery possui filas declaradas `default` e `integrations`; somente
  `default` tem tarefas nesta fase.
- migrations rodam em serviço de release explícito.

## Segurança multiempresa

A organização autorizada é selecionada explicitamente na jornada de
organizações, persistida na sessão e revalidada contra Membership ativa em
cada acesso. Nenhum ID enviado autoriza uma operação sozinho. Services e
selectors recebem `organization` explicitamente. O User não armazena papel
organizacional e pode participar de várias organizações.

Criação e merge de clientes, além da criação de produto, registram eventos
reais na outbox. Alterações relevantes são auditadas sem documento, contato,
conteúdo de nota ou descrição livre nos payloads.
