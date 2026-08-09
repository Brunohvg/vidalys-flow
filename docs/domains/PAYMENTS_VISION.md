# Plano proposto de Payments — Fase 5

Status: plano aprovado em 8 de agosto de 2026; implementação candidata em
andamento, sem autorização de sandbox, PR, merge, release ou deploy.

Payments será um domínio greenfield e independente. O planejamento não
consultou Flowlog e proíbe qualquer reutilização de código, banco, IDs,
credenciais, webhooks, endpoints, runtime ou infraestrutura antigos.

## Objetivo da fase

Criar um núcleo canônico para links de checkout hospedado, sempre em BRL e no
valor integral persistido de um `Order` confirmado. O primeiro rollout
proposto é Mercado Pago Checkout Pro; o segundo é Pagar.me v5 Payment Links.
Appmax permanece posterior.

Nenhum checkout transparente será construído. A Vidalys Flow nunca receberá
número completo de cartão, CVV ou dados de autenticação do portador.

## Fluxo canônico

```text
Order confirmed
  → PaymentIntent com valor BRL congelado
  → PaymentAttempt único e idempotente
  → outbox/worker solicita checkout hospedado
  → link ativo para compartilhamento manual
  → callback autenticado e deduplicado
  → consulta autoritativa ao provider
  → estado canônico atualizado
  → audit/outbox sanitizados
```

Somente um attempt poderá estar solicitado, ativo ou processando por intent.
Trocar de provider exigirá fechamento verificado do attempt anterior. Não
haverá fallback automático porque dois links pagáveis criam risco de cobrança
duplicada.

## Modelos propostos

- `PaymentIntent`: raiz por Organization e Order, valor imutável, estado e
  versão;
- `PaymentAttempt`: tentativa e link hospedado de um provider;
- `PaymentProviderAccount`: configuração não secreta e referência opaca ao
  canal de secrets;
- `PaymentStatusHistory`: histórico imutável separado de AuditEvent;
- `PaymentCommandReceipt`: idempotência dos comandos internos;
- `PaymentWebhookReceipt`: deduplicação sanitizada, nunca callback bruto.

Estados de intent propostos: `pending`, `awaiting_payment`, `processing`,
`paid`, `cancelled`, `expired` e `requires_attention`. Estados do provider não
serão copiados diretamente para o agregado.

## Dinheiro e Order

- moeda canônica: BRL;
- dinheiro: `Decimal(14,2)`, `ROUND_HALF_UP`;
- conversão para centavos somente no adapter e com validação exata;
- valor sempre derivado de `Order.grand_total` persistido;
- sem pagamentos parciais, split, moeda estrangeira, taxas, juros, desconto
  do provider ou alteração dos totais de Orders;
- Payments importa Orders; Orders não importa Payments;
- pagamento não muda `Order.status` nem conclui Fulfillment.

O cancelamento do Order fechará intents ainda abertos quando o provider
confirmar o encerramento. Um pagamento já confirmado em Order cancelado irá
para `requires_attention`; reembolso automático está fora da fase.

## Providers

### Mercado Pago

Checkout Pro é a primeira integração proposta porque mantém o pagamento no
ambiente hospedado e a documentação oficial atual descreve callback com chave
secreta para validar a origem. Mesmo após validar a assinatura, o worker deverá
consultar o recurso autoritativo antes de mudar o estado canônico.

### Pagar.me

Payment Links v5 é a segunda integração proposta. A API oficial possui links,
ambiente/chaves de teste e webhooks com reenvio, mas a documentação pública
revisada não estabeleceu de forma suficiente a autenticação de origem do
callback. O recebimento ficará desabilitado até confirmação oficial e Review
de Segurança. Correlação de conta e nova consulta à API são obrigatórias, mas
não serão tratadas silenciosamente como substitutas da autenticação.

### Appmax

O material público oficial confirma links de pagamento e disponibilidade via
API, mas não oferece ainda evidência suficiente do contrato técnico completo
de autenticação, webhook, idempotência e sandbox necessário. O adapter fica
adiado até o núcleo e os dois primeiros providers estarem estáveis.

## Segurança de callbacks

Callbacks podem carregar documento, contato, endereço e metadados de cartão.
O corpo e os headers serão processados apenas em memória, com limite de
tamanho, sem log e sem persistência. O receipt guardará somente identificadores
sanitizados e digest.

Organization será derivada da configuração interna do provider account, nunca
de um ID enviado no payload. Replays, eventos repetidos, fora de ordem,
cross-account e cross-Organization terão testes diretos.

## Autorização

- OWNER, ADMIN e MANAGER: criar intent, escolher provider habilitado, solicitar
  ou cancelar link e reconciliar;
- OPERATOR: consultar estado e copiar o link ativo para compartilhamento
  manual;
- somente manager tier: referências externas, provider account, evidência de
  callback/reconciliação e detalhes de `requires_attention`.

Messaging não faz parte desta fase; o sistema não enviará links sozinho.

## Efeitos externos

Implementação e CI usarão fakes e fixtures de contrato, com rede bloqueada.
Qualquer chamada sandbox exigirá autorização humana separada, credencial de
teste por canal seguro e evidência sanitizada. Credenciais de produção,
registro público de webhook, cobrança real e deploy continuam proibidos.

## Referências oficiais verificadas

- Mercado Pago Checkout Pro:
  <https://www.mercadopago.com.br/developers/pt/docs/checkout-pro/overview>;
- Mercado Pago Webhooks:
  <https://www.mercadopago.com.br/developers/pt/docs/checkout-pro/payment-notifications>;
- Pagar.me v5 Payment Links: <https://docs.pagar.me/reference/criar-link>;
- Pagar.me Webhooks: <https://docs.pagar.me/docs/webhooks>;
- Appmax: <https://www.appmax.org/>.

Pesquisa realizada em 8 de agosto de 2026. Capacidades de provider deverão ser
revalidadas antes da implementação e novamente antes de sandbox/produção.

## Decisões humanas aprovadas

1. pagamento integral do Order e somente um attempt ativo;
2. Mercado Pago primeiro, Pagar.me segundo e Appmax posterior;
3. Pagar.me callback bloqueado até confirmação oficial de autenticidade;
4. permissões gerenciais para mutações e OPERATOR apenas para estado/link;
5. `requires_attention` sem reembolso automático para conflitos financeiros;
6. Pix, boleto e cartão apenas no checkout hospedado;
7. nenhuma rede na implementação/CI e sandbox somente com nova autorização.

A aprovação deste plano liberou somente a implementação candidata. Não
autoriza sandbox, PR, merge, release, provider em produção ou deploy.
