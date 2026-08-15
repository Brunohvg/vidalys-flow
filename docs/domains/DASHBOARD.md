# Dashboard and complete experience

## Purpose

Phase 08 established an Organization-scoped operational read layer over the
approved Vidalys Flow domains. Phase 10 extends that experience with global
search, operational presets, pickup center, Order Workspace actions and
reports, without giving Dashboard ownership of a business lifecycle.

The dashboard answers operational questions such as what needs attention now,
which orders are active, and how an Order relates to Payment, Fulfillment and
transactional Messaging. Canonical mutations remain in the owning domain.

## Organization boundary

Every dashboard selector receives an `Organization` resolved from the
authenticated user's active `Membership`. Request data never chooses an
arbitrary Organization. Cross-Organization records are filtered before
composition, and a workspace request for an Order outside the active
Organization returns 404.

## Read-model dependencies

- Orders provide the primary operational axis, recent-order list and report
  source;
- Payments contribute `requires_attention`/`expired` work items and payment
  context for an Order;
- Fulfillment contributes open work in `draft`, `preparing`, `ready` and
  `in_transit` plus pickups elegíveis;
- Messaging contributes `failed` and `uncertain` transactional messages;
- Integrations contributes degraded connections and `failed`/`uncertain`
  deliveries;
- Customers and Products contribute Organization-scoped global search results.

No dashboard state is written back into these domains, and no state is
reinterpreted into a competing lifecycle.

## Attention queues and operational presets

Attention queues are bounded operational lists. They are not inboxes, task
models or workflow records. A queue item links users back to the owning
canonical domain or to the Order workspace.

Orders exposes presets operacionais como Hoje, Rascunhos, Confirmados e
Cancelados. Esses presets são apenas consultas pré-definidas; não criam estado,
SavedFilter persistido, tarefa ou workflow.

O dashboard não é um inbound WhatsApp sales inbox. Conversas inbound de venda
exigem escopo de domínio separado.

## Global search

A operação rápida da Dashboard pesquisa Orders, Customers e Products sempre na
Organization ativa. O resultado é separado por tipo e direciona para a
superfície canônica da entidade. Busca não concede acesso além das policies do
domínio e não retorna registros de outra Organization.

## Order Workspace

O workspace compõe Order, Customer context, PaymentIntent, Fulfillments e
Mensagens relacionadas. Na Fase 10 ele também pode apresentar uma `Próxima
ação` contextual e comandos operacionais válidos, mas cada ação delega ao
service/policy do domínio proprietário. Dashboard não cria lifecycle ou
permissão própria para essas mutações.

## Central de Retiradas

A Central de Retiradas deriva uma fila Organization-scoped de Fulfillments de
pickup elegíveis. Número do pedido pode localizar a operação, mas não substitui
a validação segura de retirada. Código/QR e confirmação humana permanecem parte
da experiência antes do comando canônico de conclusão de Fulfillment.

## Relatórios

Relatórios da Fase 10 são somente leitura e derivados de Orders canônicos.
Períodos disponíveis incluem hoje, ontem, últimos 7 dias, mês atual, mês
anterior, ano atual e intervalo personalizado.

O intervalo personalizado usa datas inclusivas na UI e uma janela interna
`[start, end)` para evitar ambiguidade de horário. Parâmetros inválidos fazem
fallback seguro para o mês atual. A comparação usa uma janela imediatamente
anterior de igual duração.

Resumo e série diária são sempre Organization-scoped. Exportação CSV reutiliza
o mesmo intervalo resolvido pela página e não persiste uma segunda fonte de
verdade. Os relatórios são operacionais, não fiscais, e não alteram dinheiro,
estados ou receipts.

## Privacy

A Dashboard expõe apenas campos necessários para reconhecimento operacional.
Ela não deve expor provider credentials, webhook secrets, raw callback
payloads, arbitrary integration metadata, PII fora das policies dos domínios
ou outros dados sensíveis.

## HTTP and persistence

As superfícies de leitura da Dashboard são endpoints autenticados `GET` e não
criam models próprios. Ações exibidas no workspace continuam passando pelos
domínios proprietários, preservando autorização, idempotência, concorrência e
auditoria.

## External effects

Phase 10 não ativa provider real, sandbox, credencial, callback público,
deploy, infraestrutura, produção ou cutover. Integrações/CEP permanecem
provider-neutral e fail-closed para efeitos externos não autorizados.
