# Arquitetura

## Produto aprovado

A Vidalys Flow é um monólito modular Django. A fundação possui somente:

- `core`: primitivas sem dependência de domínio;
- `users`: identidade nativa por e-mail;
- `organizations`: organizações, unidades e Membership;
- `audit`: eventos de auditoria imutáveis e sanitizados;
- `platform`: outbox, guardrails, tarefas e healthchecks.
- `customers`: identidade, contatos, endereços, notas e merge;
- `products`: catálogo operacional, variantes e identificadores.
- `orders`: pedidos comerciais, itens snapshot, estados e totais.

O grafo permitido é:

```text
users         → core
organizations → core, users
audit         → core, users, organizations
platform      → core, audit, organizations
customers     → core, users, organizations, audit, platform
products      → core, users, organizations, audit, platform
orders        → core, users, organizations, customers, products, audit, platform
```

`core` nunca importa outro app local. Não existem runtime alternativo,
middleware de organização, hostname tenancy ou compatibilidade de tabelas.
Customers e Products não importam um ao outro nem importam Orders. Orders
consome apenas os contratos aprovados desses domínios.

## Próximo módulo planejado

Fulfillment será implementado somente depois da aprovação humana de seu plano.
O grafo proposto acrescenta uma dependência unidirecional:

```text
fulfillment → core, users, organizations, orders, audit, platform
```

Orders não importará Fulfillment. O módulo novo consumirá snapshots e eventos
internos aprovados de Orders, sem mudar seus estados comerciais. Não haverá
estoque, pagamento, transportadora, provider ou efeito externo na Fase 4.

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

Orders deriva a organização da Membership ativa, usa numeração crescente
independente por organização e trata o pedido como agregado concorrente.
Comandos mutáveis possuem recibo idempotente; edições e transições bloqueiam
o agregado e validam sua versão esperada. Eventos da outbox permanecem
internos e não publicam para providers nesta fase.
