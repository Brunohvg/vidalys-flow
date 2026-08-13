# Plano proposto de Messaging — Fase 6

Status: checkpoint de planejamento pendente de aprovação humana.

Messaging será um domínio greenfield da Vidalys Flow. Este planejamento usa
somente contratos já aprovados do próprio repositório e documentação oficial
atual. O Flowlog não foi consultado e não poderá fornecer código, contatos,
templates, mensagens, conversas, banco, IDs, credenciais, runtime, providers
ou infraestrutura.

## Objetivo da fase

Enviar comunicações transacionais rastreáveis a partir de fatos já aprovados
de Orders, Fulfillment e Payments. O primeiro caso operacional é compartilhar
de forma segura um link de checkout que Payments já marcou como ativo; a fase
também propõe confirmação do pedido, progresso logístico e confirmação de
pagamento.

O núcleo será independente de canal. O rollout proposto é:

1. WhatsApp Business Platform Cloud API com templates utilitários aprovados;
2. e-mail transacional por Amazon SES;
3. outros canais somente em fases posteriores.

Implementação e CI continuarão sem rede. Nenhum envio real, credencial,
assinatura pública de webhook, template no provider, domínio de e-mail,
sandbox ou produção fica autorizado por este plano.

## Fluxo canônico

```text
evento interno aprovado ou comando manual permitido
  → regra Organization-scoped habilitada ou caso manual allowlisted
  → fonte, Customer, ContactPoint e permissão revalidados
  → Message com template/variáveis fechados e versionados
  → outbox + worker da fila integrations
  → revalidação final da fonte e do destino
  → adapter desabilitado/fake no CI
  → aceitação do provider = sent, não delivered
  → callback autenticado e deduplicado
  → estado canônico monotônico + histórico/audit sanitizados
```

Cada regra automática começa desabilitada por Organization. O payload da
outbox serve para roteamento, nunca como autorização ou conteúdo confiável. O
worker relê o agregado original e bloqueia o envio quando a realidade mudou.

## Agregados propostos

- `Message`: raiz transacional, fonte, template, canal, destino minimizado,
  propósito, estado e versão;
- `MessageDeliveryAttempt`: tentativa serializada, lease, backoff, correlação
  externa sanitizada e resultado;
- `MessageTemplate`: template fechado, versionado e imutável depois do uso;
- `MessagingChannelAccount`: configuração não secreta de remetente e alias
  opaco para secrets;
- `MessagingPreference`: permissão ou supressão por contato, canal e propósito,
  com proveniência e versão de política;
- `MessageAutomationRule`: evento allowlisted → template/canal, desabilitada por
  padrão;
- `MessageStatusHistory`: histórico imutável separado de `AuditEvent`;
- `MessageCommandReceipt`: idempotência de comandos;
- `MessageWebhookReceipt`: deduplicação de callback autenticado, nunca body
  bruto.

Estados propostos para `Message`: `pending`, `queued`, `sending`, `sent`,
`delivered`, `failed`, `cancelled` e `requires_attention`.

`sent` significa somente que o provider aceitou a solicitação. `delivered`
depende de evidência autenticada. Sinais de abertura, clique ou leitura não
entram no ciclo canônico. Um provider não pode impor seus nomes de estado ao
domínio.

## Fontes permitidas

Automação poderá existir apenas para versões aprovadas destes eventos:

- `order.confirmed`;
- `fulfillment.ready`;
- `fulfillment.dispatched`;
- `fulfillment.completed`;
- `payment.checkout_activated`;
- `payment.status_changed`, somente quando mapeado a confirmação de pagamento.

Um envio manual também deverá apontar para pedido, fulfillment ou pagamento
e template allowlisted. Texto livre, marketing e mensagens sem fonte ficam
estruturalmente proibidos.

### Link de pagamento

O link não será aceito do navegador nem copiado de um evento. Antes de enviar,
o worker relerá a tentativa exata de Payments e comprovará que ela continua
ativa, na mesma Organization e ligada ao intent esperado. Link expirado,
cancelado, substituído ou em `requires_attention` bloqueia o envio.

Messaging não altera estados, valores ou snapshots de Payments e Orders. O
link completo não entra em audit, outbox, receipts, logs, métricas ou erros.

## Templates e conteúdo

Templates possuem chave semântica, canal, locale, versão e schema fechado de
parâmetros. Uma versão já usada é imutável. Parâmetros aceitos serão escalares
mínimos, como nome de exibição, número do pedido, estado logístico e referência
ao link ativo.

O corpo renderizado e respostas brutas do provider não serão persistidos. A
implementação deve escapar conteúdo por canal e impedir HTML, variáveis,
URLs ou campos extras fora do schema. Templates no provider serão apenas
referenciados; criação e aprovação remotas ficam fora desta fase.

## Permissão, LGPD e supressão

Ter um telefone ou e-mail em Customers não equivale a autorização de envio.
Cada dispatch exigirá:

- `Customer` canônico não mesclado;
- `ContactPoint` ativo, correto para o canal e explicitamente selecionado;
- evidência vigente por canal e finalidade transacional;
- ausência de opt-out, complaint, hard bounce ou supressão;
- regra/template/account ativos na mesma Organization.

A Organization continua responsável por escolher e documentar a hipótese
legal aplicável. A Vidalys Flow registra a decisão e a aplica; não inventa
consentimento nem legítimo interesse. A orientação da ANPD exige análise
concreta de finalidade, necessidade, expectativas e salvaguardas quando se
usa legítimo interesse.

Customer mesclado ou contato alterado entre criação e dispatch bloqueia a
mensagem. Não haverá repontamento silencioso para o Customer ou contato novo.

## Concorrência, retry e duplicidade

Somente uma tentativa ativa poderá existir por mensagem. O envio ocorrerá
fora da transação, após lease persistente e revalidação. O worker deverá
preservar uma chave/correlação estável.

O Amazon SES documenta que, raramente, pode aceitar um e-mail apesar de o
cliente receber erro; um retry pode então duplicá-lo. A mesma classe de
ambiguidade deve ser tratada em qualquer canal: se o adapter não provar
idempotência do envio, timeout após possível aceitação vai para
`requires_attention`, sem retry cego e sem fallback automático.

Callbacks repetidos ou fora de ordem não podem regredir `delivered`. Evidência
conflitante é preservada de forma sanitizada para reconciliação gerencial.

## Canais propostos

### WhatsApp Cloud API

A coleção oficial da Meta confirma envio de templates, IDs por mensagem e
status por webhook. Templates devem existir no WhatsApp Manager/API e o ID
externo serve para correlação. A própria documentação alerta que notificações
de status podem chegar fora de ordem.

A fase enviará somente template utilitário aprovado. Mensagem de sessão livre,
marketing, catálogo, mídia, WhatsApp Flows, resposta inbound e chatbot ficam
fora do escopo. O callback de status só poderá ser habilitado depois de seu
contrato de autenticidade ser implementado e revisado.

### Amazon SES

O adapter proposto enviará uma mensagem por destinatário, com versões texto e
HTML, identidade de remetente verificada e tags opacas de correlação. Aceitação
do `SendEmail` não será tratada como entrega.

Eventos de delivery, bounce e complaint usarão SES/SNS. Antes do processamento,
a assinatura SNS deverá ser validada, inclusive origem HTTPS do certificado,
cadeia confiável, `TopicArn` esperado, timestamp/replay e versão de assinatura.
Headers e conteúdo original não serão solicitados nem persistidos.

## Autorização

- OWNER, ADMIN, MANAGER e OPERATOR: listar mensagens, ver destino mascarado e
  solicitar envio manual de um template transacional já habilitado para uma
  fonte e contato elegíveis;
- OWNER, ADMIN e MANAGER: configurar contas, templates, automações,
  permissões/supressões, cancelar/repetir quando seguro, reconciliar e ver
  destino completo/evidência sanitizada;
- nenhum papel: texto livre, marketing, bypass de supressão, ativação de rede
  ou alteração dos domínios de origem.

Workers, callbacks, admin, services e selectors terão isolamento organizacional
e testes cross-tenant diretos.

## Segurança e privacidade

Credenciais existirão apenas em canal futuro de secrets e o banco guardará
somente alias opaco. Callback bruto será limitado, autenticado, processado em
memória e descartado. Destinos completos, conteúdo, checkout URL, headers,
tokens, assinaturas e diagnósticos não entram em logs, AuditEvent, OutboxEvent,
receipts, exceções ou métricas.

Open, click e read tracking ficam desativados. Conteúdo inbound do WhatsApp não
será armazenado. Endpoints públicos falham fechados, derivam Organization da
conta configurada e nunca confiam em um `organization_id` do caller.

## Efeitos externos e máquina independente

O código candidato usará fakes e fixtures com rede bloqueada. Uma validação em
sandbox exigirá nova autorização humana, contas de teste exclusivas, números e
e-mails de teste designados e evidência sanitizada. Produção continua para as
Fases 9 e 10.

Nada será executado na máquina, banco, Redis, WhatsApp, e-mail ou infraestrutura
do Flowlog. A futura máquina da Vidalys Flow será exclusiva, mas seu
provisionamento ainda não está comprovado e pertence à Fase 9.

## Referências oficiais verificadas

- Meta, coleção oficial WhatsApp Business Platform:
  <https://www.postman.com/meta/whatsapp-business-platform/overview>;
- Meta, envio e tracking de mensagens:
  <https://www.postman.com/meta/whatsapp-business-platform/folder/o48mro7/messages>;
- Meta, notificações de status fora de ordem:
  <https://www.postman.com/meta/whatsapp-business-platform/request/rgtfq23/message-status-update-notifications>;
- AWS, processamento de envio do SES:
  <https://docs.aws.amazon.com/ses/latest/dg/send-email-concepts-process.html>;
- AWS, eventos do SES:
  <https://docs.aws.amazon.com/ses/latest/dg/monitor-using-event-publishing.html>;
- AWS, verificação de assinatura SNS:
  <https://docs.aws.amazon.com/sns/latest/dg/sns-verify-signature-of-message.html>;
- ANPD, guia de legítimo interesse:
  <https://www.gov.br/anpd/pt-br/assuntos/noticias/anpd-lanca-guia-orientativo-sobre-legitimo-interesse>;
- ANPD, guia de segurança da informação:
  <https://www.gov.br/anpd/pt-br/centrais-de-conteudo/materiais-educativos-e-publicacoes/guia-orientativo-sobre-seguranca-da-informacao-para-agentes-de-tratamento-de-pequeno-porte>.

Pesquisa realizada em 12 de agosto de 2026. Contratos de provider deverão ser
revalidados antes da implementação e novamente antes de sandbox/produção.

## Decisões humanas necessárias

1. aprovar Messaging somente transacional, sem marketing, campanhas, inbound,
   chatbot, IA, SMS ou anexos;
2. aprovar WhatsApp Cloud API como canal A e Amazon SES como canal B;
3. aprovar o allowlist de eventos e regras automáticas desabilitadas por padrão;
4. aprovar que contato não basta: permissão por finalidade é obrigatória e
   supressão sempre falha fechado;
5. aprovar envio manual por OPERATOR somente com fonte/template habilitados,
   mantendo configuração e evidência completa no manager tier;
6. aprovar estados canônicos e exclusão de open/click/read;
7. aprovar ausência de retry cego e fallback automático após resultado ambíguo;
8. aprovar fakes/fixtures sem rede e novo checkpoint para qualquer sandbox ou
   efeito externo.

A aprovação deste plano liberará somente a implementação candidata. Não
autoriza sandbox, envio real, callback público, credenciais, templates remotos,
PR, merge, release, deploy ou fase posterior.
