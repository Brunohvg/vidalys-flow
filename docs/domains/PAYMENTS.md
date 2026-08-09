# Payments — contrato implementado no candidato da Fase 5

Status: implementação candidata. Este documento não aprova Review, QA,
sandbox, provider, PR, merge, release ou deploy.

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
regressivo e cancelamento de Order com tentativa aberta ou pagamento já
confirmado. Não existe reembolso automático nesta fase.

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
rede. Um dispatcher aceita adapter injetado, executa I/O fora da transação e
só então ativa o link sob novo lock. O adapter padrão bloqueia efeitos
externos.

### Callback e reconciliação

O callback Mercado Pago:

1. resolve a conta pela rota interna, nunca por Organization do payload;
2. exige JSON e tamanho máximo de 64 KiB;
3. aplica limite por conta e origem no cache Redis, falhando fechado;
4. calcula SHA-256 sem persistir o body;
5. valida `X-Signature`, `X-Request-Id` e janela de cinco minutos;
6. busca o recurso autoritativo por loader injetado;
7. valida conta, ID, valor e moeda;
8. deduplica o evento e aplica transição monotônica.

Sem canal de secrets e loader aprovados, a rota responde indisponível e não
faz rede. O callback Pagar.me é bloqueado por código e constraint até que sua
autenticidade tenha evidência oficial e Review de Segurança.

Reconciliação manual usa o mesmo recurso autoritativo, receipt idempotente,
`expected_version` e locks. O fetch ocorre antes da transação de aplicação.

## Cancelamento de Order

O consumer interno lê `order.cancelled` da outbox:

- intent pendente sem checkout aberto → `cancelled`;
- checkout solicitado/ativo/processando ou pagamento confirmado →
  `requires_attention`;
- nenhuma alteração em Order/Fulfillment;
- nenhum refund ou cancelamento externo automático.

## Autorização e privacidade

- OWNER, ADMIN, MANAGER: criar intent e solicitar/reconciliar checkout;
- OPERATOR: listar, consultar estado e copiar somente link ativo;
- evidência externa, nome do cliente e códigos de atenção: manager tier;
- alias de credencial, assinatura, token, callback bruto, documento, contato e
  endereço não entram em audit/outbox/log/receipt;
- URL hospedada fica apenas no PaymentAttempt e na tela operacional autorizada.

## Providers

Mercado Pago Checkout Pro e Pagar.me Payment Links possuem builders de
contrato locais. Ambos herdam adapters que recusam rede. Appmax está ausente e
permanece adiado. Pix, boleto e cartão existem somente como opções do checkout
hospedado; a Vidalys Flow não renderiza QR/PDF nem recebe PAN/CVV.

## Operação e incidentes

- callback inválido/malformado/replay: resposta genérica, sem log do body;
- timeout após criação externa: reutilizar a mesma chave do attempt e
  reconciliar, nunca criar outro link automaticamente;
- valor/moeda divergente: `requires_attention`, bloquear nova tentativa;
- dois pagamentos externos: preservar evidência e encaminhar para processo
  manual futuro; não inventar crédito ou refund;
- indisponibilidade do provider: manter estado canônico, sem fallback;
- rotação de credencial: pertence à ativação posterior do canal de secrets.

## Testes e execução

Os testes usam PostgreSQL 17 e fakes `external = False`. Cobrem autorização,
cross-Organization, idempotência, versão, tentativa única, concorrência,
assinatura, replay, tamanho, callback duplicado, valor/moeda, cancelamento,
masking, contracts e rede desabilitada. SQLite e chamadas sandbox não são
aceitos.
