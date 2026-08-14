# Integrations — visão da Fase 07

## Status

Planejamento iniciado e plano técnico aprovado em 14 de agosto de 2026. A implementação está autorizada somente para o núcleo provider-neutral, adapter de referência e fakes offline. Provider real, credenciais, sandbox, callbacks públicos, PR, merge e deploy continuam não autorizados.

## Objetivo

Criar uma fronteira canônica e provider-neutral para integrações externas da Vidalys Flow. Sistemas externos podem transportar comandos, eventos e evidências, mas nunca ditam diretamente o estado canônico de Orders, Fulfillment, Payments ou Messaging.

A fase resolve egress confiável, ingress autenticado e reconciliação de estados incertos. Tudo é Organization-scoped, idempotente, auditável e fail-closed.

## Dependências e direção

A implementação nasce da `main` em `09d73050f1df9d52b13e61ae87a26db4b26f365c` e depende do produto aprovado da Fase 06 em `e2140eb25cc10f1a79dad05a0507ba9141003ac9`.

```text
integrations → core, users, organizations, audit, platform
             → customers, products, orders, fulfillment, payments, messaging
```

Domínios canônicos não importam adapters, clientes HTTP, SDKs ou modelos específicos de Integrations. Saída parte de contrato/evento canônico; entrada só pode chamar comando público e aprovado do domínio-alvo.

## Núcleo

O núcleo contém `IntegrationConnection`, `IntegrationEndpoint`, `IntegrationDelivery`, `IntegrationDeliveryAttempt`, `IntegrationWebhookReceipt` e `IntegrationReconciliationRun`.

Egress usa a fila Celery `integrations`, lease, retry limitado e backoff. I/O externo não roda em transação. Aceitação ambígua termina em `uncertain`, sem retry cego.

Ingress resolve conexão/endpoint, autentica origem, protege contra replay, deduplica e valida versão exata do contrato antes de qualquer tradução canônica. Tenant nunca vem de `organization_id` fornecido no payload.

## Referência offline

A Fase 07 não exige Nuvemshop, ERP, marketplace ou outro conector comercial. A arquitetura é validada por um `ReferenceAdapter` determinístico e fakes offline que simulam sucesso, falha transitória, falha permanente, timeout/aceitação ambígua e reconciliação. A rede externa permanece bloqueada.

Qualquer conector concreto futuro exige checkpoint próprio com capacidades, direção, contratos/versionamento, autenticação, idempotência, erros/retry, timeout, reconciliação, PII, rate limits e critérios separados de sandbox/produção.

## Segurança

Configuração persistida é não secreta; credenciais ficam somente por aliases opacos. Raw webhook body, headers completos, tokens, assinaturas, certificados e payloads arbitrários não são evidência canônica. Circuit breaker/degradação é isolado por Organization + conexão.

## Fora de escopo

Flowlog runtime/banco/dados, providers reais, sandbox, credenciais, callbacks públicos, HTTP arbitrário, execução de código, ERP/fiscal/contábil/estoque/marketing, Dashboard da Fase 08, homologação da Fase 09 e produção da Fase 10 permanecem fora da implementação autorizada.

## Próximos gates

Após implementação: execução integral dos checks no candidato, Review independente, QA/Security, handoff e aprovação humana final. PR e merge continuam checkpoints separados e não foram autorizados.
