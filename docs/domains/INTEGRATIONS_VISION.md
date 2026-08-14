# Integrations — visão proposta da Fase 07

## Status

Planejamento iniciado em 14 de agosto de 2026. Este documento é uma proposta e
não autoriza implementação. O contrato executável permanece em
`project/phases/07-integrations.json` e o plano depende de aprovação humana
explícita antes de qualquer código de domínio.

## Objetivo

Criar uma fronteira canônica e provider-neutral para integrações externas da
Vidalys Flow. Sistemas externos podem transportar comandos, eventos e evidências,
mas nunca ditam diretamente o estado canônico de Orders, Fulfillment, Payments
ou Messaging.

A Fase 07 deve resolver três problemas centrais: egress confiável, ingress
autenticado e reconciliação de estados incertos. Tudo é Organization-scoped,
idempotente, auditável e fail-closed.

## Dependências

A fase nasce da `main` após a aprovação da Fase 06 e depende do produto aprovado
em `e2140eb25cc10f1a79dad05a0507ba9141003ac9`.

```text
integrations → core, users, organizations, audit, platform
             → customers, products, orders, fulfillment, payments, messaging
```

A direção inversa não é permitida. Domínios canônicos não importam adapters,
clientes HTTP, SDKs ou modelos específicos de Integrations. Quando um domínio
precisar produzir integração, ele publica um contrato/evento canônico; quando
precisar receber uma mudança, Integrations chama um comando público e aprovado
do domínio-alvo.

## Núcleo proposto

O núcleo deve conter conexões externas por Organization, endpoints versionados,
deliveries de saída, tentativas serializadas, receipts de webhook e execuções de
reconciliação. Configuração não secreta pode ser persistida; tokens, chaves,
segredos e certificados ficam apenas atrás de aliases opacos.

O egress usa transactional outbox e a fila Celery `integrations`. O I/O de rede
fica fora de transações. Cada delivery possui no máximo uma tentativa ativa e
aceitação ambígua termina em `uncertain`, nunca em retry cego.

O ingress resolve primeiro a conexão/endpoint, autentica a origem, aplica
proteção contra replay, deduplica e valida a versão exata do contrato. Somente
depois disso o payload minimizado pode virar comando/evento canônico.

## Segurança e isolamento

Nenhum `organization_id` vindo do payload externo é confiável. O tenant é
resolvido pela conexão autenticada. Cross-Organization deve falhar antes de
qualquer mutação.

Payload bruto não é evidência canônica. Por padrão são persistidos apenas IDs
externos estritamente necessários, digest, timestamps, versão do contrato,
código de resultado sanitizado e campos escalares explicitamente allowlisted.
PII, headers completos, tokens e corpos integrais não entram em logs,
`AuditEvent`, `OutboxEvent` ou receipts.

Erros de autenticação, autorização e schema são permanentes e não fazem retry.
Timeout e indisponibilidade podem fazer retry limitado quando não houver risco
de duplicar um efeito já aceito. O circuit breaker é isolado por conexão e
Organization.

## Primeira tranche

O planejamento estrutural é independente de provider. A seleção dos conectores
concretos da primeira tranche ainda precisa de aprovação humana. Antes dessa
decisão, adapters devem permanecer apenas como contratos/fakes offline, sem
credenciais, sandbox, URLs públicas ou chamadas reais.

Cada conector aprovado posteriormente deverá declarar:

- capacidades e direção de dados;
- contratos de eventos/comandos e versões;
- mecanismo de autenticação de entrada;
- semântica de idempotência do provider;
- classificação de erros e política de retry;
- tratamento de timeout/aceitação ambígua;
- estratégia de reconciliação;
- minimização de payload e PII;
- limites de rate, backoff e circuit breaker;
- critérios separados para sandbox e produção.

## Fora de escopo

Não pertencem à Fase 07: integração com banco/runtime do Flowlog, importação
legada em massa, ERP/fiscal/contábil/estoque/marketing, callbacks arbitrários
programáveis pelo usuário, execução de código remoto, dashboard da Fase 08,
provisionamento/homologação da Fase 09 e produção/cutover da Fase 10.

## Gate de implementação

O checkpoint atual termina no planejamento. Para liberar implementação é
necessário aprovar explicitamente o manifesto, os modelos/lifecycles propostos,
os primeiros conectores e seus contratos de ingresso/egresso. Até essa
aprovação, `implementation_status` permanece `blocked`.
