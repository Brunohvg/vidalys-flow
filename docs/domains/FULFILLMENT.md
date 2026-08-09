# Domínio Fulfillment — Fase 4

Este contrato foi aprovado para implementação em 8 de agosto de 2026. A
aprovação não autoriza merge, deploy ou aprovação da fase concluída.

## Implementação aprovada

O domínio está implementado em `apps.fulfillment`, com migrations novas,
services transacionais, selectors tenant-scoped, policies, recibos
idempotentes, histórico imutável, eventos internos, tarefa Celery e interface
HTML em `/fulfillment/`. O material em `70364bc7` recebeu Review independente
02 `APPROVED`, QA/Segurança `GO` e ratificação humana final após a auditoria de
governança. O código está na `main`; release e deploy continuam separados e
não autorizados.

O Review independente 01 identificou inversão na ordem de locks e lacunas de
evidência concorrente, cross-organization e de sanitização. A remediação
padronizou os locks em `Order -> Fulfillment`, registrou a tarefa no Celery e
ampliou a suíte direta do domínio. PostgreSQL 17, Redis, migrations, rollback
técnico, 208 testes sem skips e 86% de cobertura foram validados no candidato.
O desvio de checkpoint ocorrido durante o merge está preservado em
`project/incidents/phase-04-governance-recovery.md`.

## Objetivo e fronteira

Fulfillment controla a execução física de um pedido confirmado: preparar,
deixar pronto, despachar uma entrega ou concluir uma retirada. Ele não altera
o estado comercial de Orders, não controla estoque e não cobra o cliente.

```text
Order confirmed
      ↓
Fulfillment batch ──→ delivery ──→ in_transit ──→ completed
      │
      └─────────────→ pickup ───────────────────→ completed
```

Um pedido pode originar vários lotes parciais. Cada lote pertence a uma única
Organization, a um único Order e a um único método. Seu identificador visual
é derivado do pedido e de uma sequência protegida por lock, por exemplo
`PED-000001-F01`.

## Agregado proposto

- `Fulfillment`: raiz, método, estado, versão, sequência por pedido, snapshots
  operacionais e timestamps;
- `FulfillmentItem`: quantidade positiva alocada de um `OrderItem` confirmado;
- `FulfillmentStatusHistory`: trilha imutável de estados do domínio;
- `FulfillmentCommandReceipt`: idempotência de comandos mutáveis.

Não haverá models de estoque, transportadora, frete, etiqueta, tracking,
pagamento, devolução ou provider nesta fase.

## Elegibilidade e quantidades

Somente `Order` confirmado e não cancelado é elegível. Criação e transições
bloqueiam e releem o pedido dentro da mesma Organization. A quantidade usa
`Decimal(12,3)`, igual a Orders.

Para cada `OrderItem`, a soma alocada em lotes não cancelados nunca pode
ultrapassar a quantidade confirmada. O cálculo e os locks incluem todos os
lotes concorrentes relevantes. Cancelar libera a alocação; concluir conserva
o fato histórico. Isso é planejamento de execução, não reserva de estoque.

## Métodos e snapshots

`delivery` exige o endereço de entrega fechado no snapshot do Order e o copia
para um schema fechado `schema_version: 1`. Não relê o endereço atual do
Customer e não aceita um endereço livre silenciosamente.

`pickup` exige uma `OrganizationUnit` ativa da mesma Organization e congela o
identificador e o nome da unidade. O cadastro atual de unidade não possui
endereço; inventar esse dado ou ampliar Organizations está fora desta fase.

Os itens usam os snapshots comerciais já congelados em Orders. Fulfillment
não relê Product, ProductVariant nem Customer e nunca recalcula dinheiro.

## Estados propostos

Estados canônicos exclusivos de Fulfillment:

- `draft`: lote alocado ainda editável;
- `preparing`: separação iniciada;
- `ready`: pronto para despacho ou retirada;
- `in_transit`: entrega despachada;
- `completed`: entrega ou retirada concluída;
- `cancelled`: execução encerrada sem conclusão.

Transições:

```text
creation   → draft
draft      → preparing | cancelled
preparing  → ready | cancelled
ready      → in_transit | cancelled       (delivery)
ready      → completed | cancelled        (pickup)
in_transit → completed | cancelled        (delivery)
```

`completed` e `cancelled` são terminais. `in_transit` é proibido para
retirada. Não há regressão, reabertura, devolução ou falha de entrega nesta
fase. `completed` não será adicionado a `Order.status`.

## Cancelamento de Order

Os ciclos comercial e logístico permanecem separados. Fulfillment consome o
evento interno e sanitizado `order.cancelled` de modo idempotente e cancela
lotes ainda abertos. Qualquer comando também relê o Order e se recusa a
avançar quando ele estiver cancelado, inclusive antes do consumidor processar
o evento.

Lotes já concluídos não são reescritos. Uma eventual devolução ou logística
reversa precisará de contrato posterior. Orders não importará Fulfillment; a
dependência continuará apontando do domínio novo para o contrato aprovado.

## Concorrência e idempotência

Todo comando mutável recebe `idempotency_key` e `expected_version`. A mesma
chave com o mesmo payload retorna o resultado anterior; payload diferente é
conflito. Locks pessimistas seguem ordem determinística e protegem pedido,
itens e lotes relevantes. Receipt, histórico, audit e outbox são persistidos
na mesma transação da mudança.

O consumidor de cancelamento deduplica pelo ID do evento de origem. Retries,
eventos repetidos ou fora de ordem não duplicam transições nem efeitos.

## Autorização e privacidade

Todas as funções exigem Membership ativa e recebem `organization`
explicitamente. OWNER, ADMIN, MANAGER e OPERATOR podem consultar, criar e
editar lotes draft e executar o fluxo operacional normal. Somente OWNER,
ADMIN e MANAGER cancelam e veem destino/contato sem máscara.

OPERATOR continua recebendo endereço, contato e documento mascarados conforme
o contrato aprovado de Orders. PII, motivo livre e instruções não entram em
AuditEvent, OutboxEvent, logs, métricas, receipts ou mensagens de erro.

## Interface da fase

A implementação oferece HTML server-rendered para lista,
filtros, detalhe, criação por pedido, edição de draft e comandos de transição.
Não haverá API pública. A interface sempre deriva Organization da sessão e
exibe progresso por quantidades sem inventar um estado novo no Order.

## Fora de escopo

- estoque, reserva, baixa, armazém e rotas de picking;
- cotação, preço de frete, etiqueta, transportadora e tracking externo;
- falha de entrega, troca, devolução, logística reversa e reembolso;
- Payments, links Mercado Pago/Pagar.me/Appmax e estados financeiros;
- Messaging, Integrations, API, importadores, fiscal e dashboard;
- infraestrutura, Coolify, homologação, produção e qualquer vínculo técnico
  com o Flowlog.

## Decisão vigente

Múltiplos lotes parciais, métodos `delivery`/`pickup`, os seis estados,
cancelamento idempotente por evento interno, permissões e itens adiados foram
aprovados para a Fase 4. Isso não autoriza deploy nem antecipa Payments,
inventory, providers, Messaging ou Integrations.
