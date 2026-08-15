# Domínio Orders

## Escopo canônico

`apps.orders` mantém o registro comercial canônico de uma `Organization`.
Orders não executa pagamento, fulfillment, mensagens, integrações, estoque,
fiscal ou efeitos externos.

A Fase 3 estabeleceu o agregado e lifecycle originais. A Fase 10 amplia a
experiência de criação sem criar um segundo lifecycle nem mover responsabilidades
de outros domínios para Orders.

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

Não existem regressões. Estados financeiros, fulfillment e provider pertencem
aos respectivos domínios. Toda transição gera um `OrderStatusHistory` imutável,
separado do AuditEvent.

## Dinheiro e fonte canônica de preço

- moeda: BRL;
- dinheiro: Decimal com 14 dígitos e duas casas;
- quantidade: Decimal com 12 dígitos e três casas;
- arredondamento: `ROUND_HALF_UP`;
- o servidor é sempre autoritativo.

A Fase 10 torna explícita a fonte monetária através de `pricing_mode`:

- `itemized`: subtotal e total derivam exclusivamente dos `OrderItem` e das
  regras monetárias históricas;
- `manual`: `manual_total` é a fonte canônica do valor da venda e o pedido pode
  possuir zero `OrderItem`.

Nenhum item fictício é criado para representar uma venda manual. Um pedido não
mantém simultaneamente duas fontes monetárias silenciosamente divergentes; a
mudança de modo exige escolha explícita enquanto o pedido ainda é editável.
Depois da confirmação, a fonte monetária e o total permanecem congelados pelas
mesmas regras de imutabilidade do Order confirmado.

Qualquer Membership ativa informa preço-base. Apenas OWNER, ADMIN ou MANAGER
aplica desconto/acréscimo em modo itemizado. Acréscimo exige motivo e não
representa frete, tributo, juros ou taxa de pagamento.

## Criação rápida e Customer inline

A Fase 10 oferece uma jornada curta para criar venda sem pré-cadastrar Customer
ou Product. A operação resolve sempre a Organization da Membership ativa e usa
os services canônicos de Customers e Orders.

- Customer existente pode ser selecionado por autocomplete Organization-scoped;
- documento exato identifica o cadastro canônico quando aplicável;
- telefone/e-mail podem sugerir cadastro existente, mas não fazem merge
  automático;
- nomes semelhantes nunca são mesclados automaticamente;
- quando o Customer não existe, sua criação ocorre atomicamente com o Order;
- a chave idempotente do quick-order é reclamada antes da criação inline, de
  modo que retry não duplica Customer nem Order;
- Product e OrderItem permanecem opcionais em `pricing_mode=manual`.

Captura de endereço é progressiva e somente aparece quando necessária para a
operação. Lookup de CEP é um contrato neutro com fallback manual; Orders não
faz chamada direta a provider.

## Snapshots e confirmação

Na confirmação, Orders congela:

- nome e documento normalizado do cliente;
- um contato operacional primário;
- endereços padrão de entrega e cobrança, quando existentes;
- nome, variante, SKU, unidade, quantidade, preço, desconto, acréscimo,
  bruto e total de cada item quando houver itens;
- a fonte canônica de preço e o total persistido do Order.

Para itens vinculados ao catálogo, nome, unidade, variante e SKU são relidos
do Product/Variant válido no instante da confirmação. Assim, alterações feitas
entre a inclusão do item e a confirmação não deixam snapshots comerciais
obsoletos.

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
Na confirmação, Customer, itens, Products e ProductVariants também são
recarregados e bloqueados em ordem determinística antes da validação e dos
snapshots. Merge ou inativação concorrente fica serializado em relação ao
instante canônico da confirmação.
O histórico rejeita alteração e exclusão tanto por instância quanto por
operações de QuerySet.

## Autorização e interface

Qualquer Membership ativa pode listar, criar, editar draft, informar preço-base
e confirmar. Manager tier também aplica ajustes, cancela e vê PII completa.

A interface HTML inclui lista, busca, filtros/presets operacionais, paginação,
criação normal, quick-order, detalhe/workspace, edição, confirmação e
cancelamento. O Order Workspace pode apresentar próximas ações de Payments,
Fulfillment e Messaging, mas sempre delega a mutação ao service/policy do
domínio proprietário. Não há API pública nem provider call direto por Orders.
