# Messaging — contrato implementado da Fase 06

Atualizado em 13 de agosto de 2026. Este documento descreve o candidato de
implementação; Review independente, QA/Security, aprovação final, PR, merge,
sandbox e deploy ainda são checkpoints separados.

## Limites e independência

Messaging é um domínio greenfield e unidirecional. Ele lê contratos aprovados
de Customers, Orders, Fulfillment e Payments e grava apenas suas próprias
entidades, AuditEvent sanitizado e OutboxEvent interno. Não importa nem se
conecta ao Flowlog, e não reutiliza código, dados, migrations, IDs, contatos,
templates, mensagens, sessões, credenciais, Redis, banco, workers, webhooks,
servidor ou configuração Evolution do sistema antigo.

O escopo é exclusivamente transacional. Marketing, campanhas, texto livre,
inbound, conversas, chatbot, IA, SMS, anexos, mídia, fallback automático,
tracking de abertura/clique e respostas ficam adiados.

## Agregado e estados

`Message` pertence a uma Organization e referencia uma fonte aprovada, sua
versão, Customer e ContactPoint exatos, template/version, canal, propósito,
evidência de permissão e parâmetros escalares allowlisted. `Message.status`
usa `pending`, `queued`, `sending`, `sent`, `delivered`, `failed`, `cancelled`
ou `uncertain`; `sent` significa aceitação do provider, não entrega.

`MessageDeliveryAttempt` serializa o dispatch com lease de 90 segundos e uma
constraint PostgreSQL permite no máximo uma tentativa ativa. Timeout, perda de
transporte ou erro inesperado após início da chamada torna o resultado
`uncertain`; não há reenvio cego nem troca automática de canal/provider.
`MessageStatusHistory`, `MessageCommandReceipt` e `MessageWebhookReceipt`
preservam, respectivamente, transições, idempotência e evidência sanitizada.

## Fontes, templates e permissões

Automação aceita somente `order.confirmed`, `fulfillment.ready`,
`fulfillment.dispatched`, `fulfillment.completed`,
`payment.checkout_activated` e `payment.status_changed`. A regra é
Organization-scoped, versionada e nasce desabilitada. O consumidor confere
tipo, ID e versão do agregado e relê a fonte; o payload do evento nunca é
autorização nem conteúdo.

Templates têm chave semântica, locale, canal, versão crescente e schema
fechado. Uma versão usada torna-se imutável tanto nas superfícies ORM quanto
por guardas PostgreSQL; os relacionamentos e snapshots de `Message` recebem a
mesma proteção. O corpo renderizado existe apenas em memória no dispatch e não
vai para banco, logs, auditoria, outbox ou receipts. O link hospedado é relido
da tentativa ativa de Payments exatamente antes do envio e nunca é copiado
para evidência operacional.

Cada envio exige Customer ativo e não mesclado, ContactPoint exato ainda ativo
e inalterado e última `MessagingPreference` ativa como `allowed` para aquele
canal e propósito. Ausência, supressão, bounce/complaint, troca de permissão,
merge ou correção do contato bloqueiam o dispatch. Não ocorre repontamento
silencioso.

## Canais e adapters

- Evolution API v2.3.7: WhatsApp linked-device `WHATSAPP-BAILEYS`, explicitamente
  não oficial, uma instância determinística por canal e apenas texto;
- WhatsApp Cloud API direta: alternativa oficial, somente template utilitário
  previamente aprovado e referenciado;
- Amazon SES: uma mensagem transacional por destinatário, texto e HTML.

Os três adapters são contratos offline e continuam herdando um bloqueio de
efeitos externos. A aplicação guarda apenas aliases opacos de secrets. Não há
client HTTP, SDK de provider, DNS, sender, credencial, sandbox ou chamada real
habilitada. Conexões nascem inativas; canal Evolution requer pareamento externo
confirmado antes de qualquer ativação futura.

## Callbacks e segurança

Callbacks públicos estão funcionalmente bloqueados porque o resolvedor de
secrets não foi ativado. O parser limita corpo e identificadores, aplica rate
limit fail-closed, deriva Organization da conexão/canal e nunca persiste o
corpo bruto. Para Evolution, um header secreto configurável é comparado em
tempo constante e é tratado como segredo compartilhado, não como assinatura
do payload. Replays são deduplicados e evidência fora de ordem é monotônica;
falha posterior a `delivered` gera uma receipt com inconsistência sem regredir
o estado.

Meta exige verificação `X-Hub-Signature-256` e SES/SNS exige assinatura X.509,
TopicArn esperado, timestamp/replay e URL de certificado confiável antes de
qualquer callback ser habilitado. Esses contratos de autenticidade permanecem
deferidos e fail-closed.

## Autorização e visibilidade

OWNER, ADMIN, MANAGER e OPERATOR podem listar mensagens, ver destino mascarado
e solicitar envio manual usando fonte, template e permissão aprovados. Apenas
OWNER, ADMIN e MANAGER configuram conexões/canais/templates/regras/preferências,
cancelam mensagens ainda não enviadas, reconciliam incerteza e veem destino e
evidência sanitizada completos. Admin é read-only e Organization-scoped.

## Operação e filas

Beat agenda consumo de fontes na fila `default` e dispatch na fila
`integrations`. O Compose possui workers exclusivos para ambas. Rede não roda
dentro de transação. A autorização final do envio trava Message, tentativa e
todas as dependências mutáveis, revalida fonte, Customer, contato, permissão,
template, canal, conexão e checkout, move o agregado para `sending` e monta o
request na mesma transação. O commit dessa transação é o ponto de linearização:
uma mudança concorrente confirmada antes dele bloqueia o envio; uma mudança
posterior fica ordenada depois do envio já autorizado. O I/O começa somente
após o commit e resultado ambíguo nunca é reenviado cegamente.

Comandos de configuração incluem todos os campos semânticos no hash
idempotente. Atualizar uma regra exige `expected_version`, trava a versão atual
e a incrementa monotonicamente; criação exige que a versão esperada seja
omitida. Desativação de template também valida a versão esperada e um template
já usado não pode ser desativado ou reescrito.

No consumidor de eventos, somente erros classificados de contrato geram
rejeição definitiva. Falhas transitórias ou inesperadas não criam receipt de
consumo e permanecem elegíveis para a próxima varredura, sem descartar o
OutboxEvent original.

Validação obrigatória: PostgreSQL 17 desde banco vazio, rollback/reaplicação da
migration Messaging, testes de domínio e concorrência, fixtures offline de
provider, topologia Celery, cobertura mínima global de 85%, scans de secrets e
independência, Ruff, Django checks, Docker e Compose.

## Próximo checkpoint

O Review independente 01 solicitou as correções P06-R01 a P06-R05. A
remediação material e sua matriz de regressão foram implementadas; o novo
candidato deve passar pelos gates e por outro Review independente. Somente
após Review sem blocker, QA/Security GO e aprovação humana final podem existir
autorização separada para PR/merge. Sandbox, providers reais, callback público,
infraestrutura e deploy continuam fora desta fase.
