# Payments — contrato implementado no candidato da Fase 5

Status: terceira remediação candidata após Review 03, aguardando validação e
nova revisão independente. Este documento não aprova Review, QA, sandbox,
provider, PR, merge, release ou deploy.

## Limite do domínio

Payments registra a intenção de cobrar exatamente o total persistido de um
Order confirmado em BRL e coordena checkout hospedado. Não calcula o pedido,
não recebe preço do navegador, não captura cartão e não altera Order ou
Fulfillment.

```text
orders ──contrato unidirecional──→ payments
payments ──evento sanitizado─────→ audit + outbox internos
payments ──adapter bloqueado─────→ provider externo (não ativado)
```

Não existe importação inversa de Payments em Orders. O Flowlog não foi
consultado nem reutilizado; não há banco, migration, ID, endpoint, credencial,
runtime, servidor ou infraestrutura compartilhada.

## Agregados persistidos

- `PaymentIntent`: um por Order, Organization explícita, valor e moeda
  imutáveis, estado canônico e `version`;
- `PaymentAttempt`: tentativa serializada de checkout hospedado;
- `PaymentProviderAccount`: provider, nome operacional e alias opaco para um
  canal futuro de secrets; nunca contém token ou signing value;
- `PaymentStatusHistory`: transições imutáveis separadas de AuditEvent;
- `PaymentCommandReceipt`: idempotência por Organization, operação e chave;
- `PaymentWebhookReceipt`: somente IDs externos sanitizados, digest e resultado
  canônico; nunca body ou headers.

O banco impõe um único attempt em `requested`, `active` ou `processing` por
intent. IDs externos são únicos dentro da conta do provider. Entidades
financeiras usam `PROTECT` e não podem ser excluídas pela aplicação.
Os snapshots de `PaymentIntent` também são protegidos no model, em `update` e
`bulk_update` e por trigger PostgreSQL, inclusive após pagamento.

## Estados

Intent:

```text
pending
  → awaiting_payment
  → processing
  → paid
  → cancelled
  → expired
  → requires_attention
```

Attempt: `requested`, `active`, `processing`, `paid`, `failed`, `cancelled` e
`expired`. Estados externos são mapeados pelo adapter e nunca copiados para
`PaymentIntent.status`.

`requires_attention` é usado para divergência de valor/moeda, evento
regressivo, resultado externo criado após mudança de contexto e cancelamento
de Order com tentativa externa aberta ou pagamento já confirmado. Callback
nunca retira o agregado desse estado; somente reconciliação gerencial ou o
fechamento verificado solicitado ao provider pode resolvê-lo. Falha conclusiva
do provider fecha o attempt como `failed` e devolve o intent a `pending`, sem
fallback automático. Uma tabela explícita proíbe regressões como
`processing → awaiting_payment`. Não existe reembolso automático nesta fase.

## Dinheiro

- moeda: BRL;
- persistência: `Decimal(14,2)`;
- origem: `Order.total` persistido e confirmado;
- conversão para centavos: somente no limite do adapter e com exatidão;
- sem parcial, split, múltiplas moedas, taxa, juros, desconto do provider,
  settlement ou contas a receber.

## Comandos

### Criar intent

Somente OWNER, ADMIN ou MANAGER com Membership ativa. O service bloqueia o
Order, revalida Organization, estado confirmado, moeda e total positivo,
copia snapshots mínimos e cria histórico, audit, outbox e receipt na mesma
transação.

### Solicitar checkout

O service valida `expected_version`, conta ativa da mesma Organization e
ausência de tentativa concorrente. Ele grava `requested` e outbox; não chama
rede. O consumidor Celery da fila `integrations` relê Order, intent, attempt e
conta antes da chamada, adquire lease de 90 segundos — maior que o hard limit
de 60 segundos do worker — e executa I/O fora da transação. Dois dispatchers
não chamam o provider simultaneamente. Timeout, bloqueio de efeito e falha de
transporte gravam somente código controlado e `dispatch_available_at` com
backoff; a mesma tentativa e chave externa são reutilizadas. Uma falha fica
isolada no item do lote e não impede o processamento dos seguintes.

Se Order, intent ou conta mudarem durante a chamada e o provider já tiver
criado o checkout, o retorno é validado e os identificadores/link são sempre
persistidos. O attempt fica `active` e o intent vai para
`requires_attention`, evitando perder evidência de um link potencialmente
pagável. O adapter padrão continua bloqueando efeitos externos.

### Cancelar link e trocar provider

OWNER, ADMIN ou MANAGER pode solicitar cancelamento. Um attempt `requested`
sem I/O em curso fecha localmente. Um link externo gera trabalho correlacionado
imutavelmente ao ID do attempt e ao evento. O worker chama o adapter fora da
transação e marca exatamente esse evento como processado quando o fluxo
termina, impedindo replay contra checkout posterior. Toda resposta
autoritativa é aplicada: `paid` preserva pagamento, valor/moeda ou estado
desconhecido gera `requires_attention`, `processing` mantém retry, e
`cancelled`/`expired` conclui o fechamento. Falhas transitórias usam o mesmo
lease e backoff controlado.

Troca de provider nunca é fallback. Depois de `failed`, `cancelled` ou
`expired`, o gerente reabre explicitamente o pagamento quando necessário e
então envia outro comando escolhendo a nova conta. A constraint continua
impedindo duas tentativas abertas.

### Callback e reconciliação

O callback Mercado Pago:

1. resolve a conta pela rota interna, nunca por Organization do payload;
2. exige JSON e tamanho máximo de 64 KiB;
3. aplica limite por conta e origem no cache Redis, falhando fechado;
4. calcula SHA-256 sem persistir o body;
5. valida `X-Signature`, `X-Request-Id` e janela de cinco minutos;
6. deriva a chave de replay do ID do recurso e `X-Request-Id` cobertos pela
   assinatura, ignorando o ID superior não autenticado do body;
7. deduplica antes de nova consulta quando o replay já é conhecido;
8. busca o recurso autoritativo por loader injetado;
9. valida conta, ID, valor e moeda e aplica somente transição monotônica.

Sem canal de secrets e loader aprovados, a rota responde indisponível e não
faz rede. O callback Pagar.me é bloqueado por código e constraint até que sua
autenticidade tenha evidência oficial e Review de Segurança.

Reconciliação manual usa o mesmo recurso autoritativo, receipt idempotente,
`expected_version` e a ordem global de locks `Order → PaymentIntent →
PaymentAttempt`. Membership gerencial ativa, Organization, intent, attempt,
conta e adapter são validados antes de qualquer guardrail ou I/O; o fetch
ocorre fora da transação de aplicação.

## Cancelamento de Order

O consumer interno lê `order.cancelled` da outbox:

- intent pendente sem checkout aberto → `cancelled`;
- checkout ainda não enviado → attempt e intent fechados localmente;
- dispatch em curso, checkout ativo/processando ou pagamento confirmado →
  `requires_attention` e preservação de eventual evidência externa;
- nenhuma alteração em Order/Fulfillment;
- nenhum refund ou cancelamento externo automático.

## Autorização e privacidade

- OWNER, ADMIN, MANAGER: criar intent, solicitar/cancelar/reabrir e reconciliar
  checkout;
- OPERATOR: listar, consultar estado e copiar somente link ativo;
- evidência externa, nome do cliente e códigos de atenção: manager tier;
- alias de credencial, assinatura, token, callback bruto, documento, contato e
  endereço não entram em audit/outbox/log/receipt;
- URL hospedada fica apenas no PaymentAttempt e na tela operacional autorizada.
- admin financeiro é somente leitura, tenant-scoped e exige Membership ativa
  de OWNER, ADMIN ou MANAGER, inclusive para object view.

## Providers

Mercado Pago Checkout Pro e Pagar.me Payment Links possuem builders comparados
com fixtures versionadas das referências oficiais. O Pagar.me v5 usa
`cart_settings.items`, `payment_settings` e limite de uma sessão paga. Ambos
herdam adapters que recusam rede. Appmax está ausente e
permanece adiado. Pix, boleto e cartão existem somente como opções do checkout
hospedado; a Vidalys Flow não renderiza QR/PDF nem recebe PAN/CVV.

## Operação e incidentes

- callback inválido/malformado/replay: resposta genérica, sem log do body;
- timeout após criação externa: reutilizar a mesma chave do attempt e
  reconciliar, nunca criar outro link automaticamente;
- valor/moeda divergente: `requires_attention`, bloquear nova tentativa;
- dois pagamentos externos: preservar evidência e encaminhar para processo
  manual futuro; não inventar crédito ou refund;
- indisponibilidade do provider: backoff persistente, erro sanitizado e sem
  fallback;
- rotação de credencial: pertence à ativação posterior do canal de secrets.

## Testes e execução

Os testes usam PostgreSQL 17 e fakes `external = False`. Cobrem autorização,
Membership inativa, admin e worker cross-Organization, idempotência, versão,
tentativa única, lease versus hard limit, backoff, falha mista sem starvation,
cancelamento concorrente ao dispatch, dois workers no mesmo cancelamento,
evento antigo após troca de provider, callback concorrente, respostas paid,
processing, mismatch e desconhecida, desativação da conta antes/durante I/O,
assinatura, replay, imutabilidade, masking e schemas fechados. Um fixture
bloqueia por DNS os hosts conhecidos de Mercado Pago e Pagar.me. SQLite e
chamadas sandbox não são aceitos.
