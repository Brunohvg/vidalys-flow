# Domínio Orders

## Escopo da Fase 3

`apps.orders` mantém o registro comercial canônico de uma `Organization`.
Orders não executa pagamento, fulfillment, mensagens, integrações, estoque,
fiscal ou efeitos externos.

## Agregado e numeração

`Order` é a raiz do agregado. Seu número é crescente e independente por
organização, armazenado como inteiro e apresentado como `PED-000001`.
`OrderNumberSequence` é bloqueado transacionalmente; a corrida de criação da
primeira sequência é decidida pela constraint de organização.

`OrderItem` aceita Product/Variant opcionais ou item avulso. Variant sempre
pertence ao Product, e todas as entidades pertencem à mesma Organization.
Vínculos usam `PROTECT`; snapshots permanecem como fonte histórica.

## Estados

Estados canônicos:

- `draft`: inicial, editável;
- `confirmed`: snapshots e valores congelados;
- `cancelled`: terminal.

Transições permitidas:

```text
criação   → draft
draft     → confirmed
draft     → cancelled
confirmed → cancelled
```

Não existem regressões. `completed`, `returned`, estados financeiros,
fulfillment e provider pertencem a fases futuras. Toda transição gera um
`OrderStatusHistory` imutável, separado do AuditEvent.

## Dinheiro

- moeda: BRL;
- dinheiro: Decimal com 14 dígitos e duas casas;
- quantidade: Decimal com 12 dígitos e três casas;
- arredondamento: `ROUND_HALF_UP`;
- bruto da linha é arredondado antes de desconto e acréscimo;
- subtotal e total são somas dos valores persistidos das linhas;
- o servidor é sempre autoritativo.

Qualquer Membership ativa informa preço-base. Apenas OWNER, ADMIN ou MANAGER
aplica desconto/acréscimo. Acréscimo exige motivo e não representa frete,
tributo, juros ou taxa de pagamento.

## Snapshots e confirmação

Na confirmação, Orders congela:

- nome e documento normalizado do cliente;
- um contato operacional primário;
- endereços padrão de entrega e cobrança, quando existentes;
- nome, variante, SKU, unidade, quantidade, preço, desconto, acréscimo,
  bruto e total de cada item.

Contato prioriza um registro marcado como primário e, em empate, WhatsApp,
telefone e e-mail. Os objetos JSON usam `schema_version: 1` e conjunto fechado
de campos.

Customer mesclado bloqueia confirmação até seleção explícita do canônico.
Product ou Variant inativo/arquivado bloqueia confirmação. Mudanças posteriores
nos cadastros nunca alteram pedido já confirmado.

`OPERATOR` recebe documento, contato e endereço mascarados. Payloads de audit,
outbox e logs nunca incluem esses dados.

## Concorrência e idempotência

Todo comando mutável recebe chave idempotente. `OrderCommandReceipt` usa
unicidade `(organization, operation, idempotency_key)` e hash canônico do
payload. Mesma chave e payload retorna o resultado anterior; payload diferente
gera conflito.

Edições e transições bloqueiam Order com `select_for_update`, recarregam o
estado atual e comparam `expected_version`. Cada mutação incrementa a versão.
Pedido, histórico, audit, outbox e receipt são gravados na mesma transação.

## Autorização e interface

Qualquer Membership ativa pode listar, criar, editar draft, informar preço-base
e confirmar. Manager tier também aplica ajustes, cancela e vê PII completa.

A fase fornece HTML server-rendered para lista, busca, filtros, paginação,
criação, detalhe, edição, confirmação e cancelamento. Não há API pública.
