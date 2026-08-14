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
- `fulfillment`: lotes parciais de entrega ou retirada, alocações e ciclo
  logístico.
- `payments`: intents financeiros canônicos, tentativas de checkout hospedado,
  callbacks verificados e reconciliação.
- `messaging`: candidato transacional outbound, templates fechados,
  permissões, canais e dispatch assíncrono com providers bloqueados.

O grafo permitido é:

```text
users         → core
organizations → core, users
audit         → core, users, organizations
platform      → core, audit, organizations
customers     → core, users, organizations, audit, platform
products      → core, users, organizations, audit, platform
orders        → core, users, organizations, customers, products, audit, platform
fulfillment   → core, users, organizations, orders, audit, platform
payments      → core, users, organizations, orders, audit, platform
```

`core` nunca importa outro app local. Não existem runtime alternativo,
middleware de organização, hostname tenancy ou compatibilidade de tabelas.
Customers e Products não importam um ao outro nem importam Orders. Orders
consome apenas os contratos aprovados desses domínios.

Payments depende de Orders em uma única direção. Orders e Fulfillment não
importam Payments; Payments não importa Fulfillment, Messaging ou
Integrations. O scanner de independência executa essas fronteiras.

## Módulo aprovado da Fase 5

Payments implementa `PaymentIntent`, `PaymentAttempt`, configuração não
secreta de provider, histórico imutável, receipts de comandos e callbacks. O
valor integral é copiado de um Order confirmado em BRL e não altera
`Order.status` nem Fulfillment.

Os adapters de Mercado Pago Checkout Pro e Pagar.me Payment Links constroem
contratos locais, mas herdam o bloqueio de efeitos externos. Testes usam fakes
com `external = False`; produção, sandbox, credenciais e registro público de
callback não estão habilitados. O callback Pagar.me é bloqueado inclusive por
constraint de banco até confirmação de autenticidade em fase posterior.

## Candidato implementado da Fase 6

Messaging depende em uma única direção dos contratos aprovados de
Customers, Orders, Fulfillment e Payments, além de core, users, organizations,
audit e platform. Nenhum desses domínios importará Messaging.

```text
messaging → core, users, organizations, customers, orders,
            fulfillment, payments, audit, platform
```

O plano limita o módulo a mensagens transacionais, templates fechados,
permissão/supressão, dispatch assíncrono e callbacks de status. Evolution API
v2.3.7 linked-device, WhatsApp Cloud API direta e Amazon SES ficam atrás de
adapters e uma matriz de capabilities, com efeitos externos desligados.
Evolution é não oficial, possui conexões e canais/instâncias separados e não
compartilha secrets com a Meta Cloud. O plano foi aprovado; o candidato ainda
depende de Review, QA/Security e aprovação humana final.

## Módulo aprovado da Fase 4

Fulfillment foi implementado depois da aprovação humana de seu plano e
ratificado após Review e QA/Segurança. O grafo acrescenta uma dependência
unidirecional:

```text
fulfillment → core, users, organizations, orders, audit, platform
```

Orders não importa Fulfillment. O módulo novo consome snapshots e eventos
internos aprovados de Orders, sem mudar seus estados comerciais. Não há
estoque, pagamento, transportadora, provider ou efeito externo na Fase 4.

## Execução

- PostgreSQL 17 é a única base suportada para domínio e testes.
- Redis DB 0 é o broker Celery.
- Redis DB 1 é o cache.
- Celery possui workers explícitos para as filas `default` e `integrations`;
  `default` contém outbox e consumidores internos, enquanto `integrations`
  isola o dispatch e o cancelamento de checkout. Um gate cruza agenda, rotas,
  tasks registradas e filas consumidas. Nenhuma tarefa financeira possui
  autorização para chamar provider nesta fase.
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

Fulfillment também recebe Organization explicitamente, bloqueia `Order` antes
de seus lotes, limita alocações à quantidade confirmada e consome
`order.cancelled` de forma idempotente. Orders não importa Fulfillment.

Payments mantém a ordem global de locks `Order → PaymentIntent →
PaymentAttempt`; a configuração de provider é validada sem introduzir lock em
ordem inversa. Dispatch e cancelamento usam lease persistente de 90 segundos,
backoff e erro controlado no attempt; uma falha de provider não interrompe o
lote. A mesma chave externa sobrevive a timeout e retry. Rede nunca ocorre
dentro de transação, e autorização/tenant são validados antes de I/O. Um
resultado externo válido é persistido mesmo se Order, intent ou conta mudarem
durante a chamada. Cancelamento usa correlação persistida attempt/evento,
consome terminalmente o evento exato e aplica qualquer evidência autoritativa
antes de decidir retry. Callback bruto existe somente em
memória, tem tamanho limitado, assinatura e janela antirreplay, é substituído
por consulta autoritativa e não entra em banco, audit, outbox ou logs.
Organization vem do `PaymentProviderAccount` resolvido pela rota, nunca do
payload externo. Replay é deduplicado pelo recurso e pelo digest do
`X-Request-Id` autenticado; IDs superiores não assinados são ignorados.
