# QA e Segurança — Fase 07 Integrations

- decisão técnica: `GO`;
- candidato material imutável: `a2c1b1d90e9c331eb4f9bb1812a5e341d9e1a90e`;
- Review independente: `complete`, sem achados bloqueantes;
- carrier validado por QA: `621f2b372fc8d0c59a7594fc24c5d796d9cd2ae9`;
- baseline (`actual_base_sha`): `09d73050f1df9d52b13e61ae87a26db4b26f365c`;
- dependency head aprovado: `e2140eb25cc10f1a79dad05a0507ba9141003ac9`;
- CI de QA: run `31805550912`, `success` no SHA `621f2b372fc8d0c59a7594fc24c5d796d9cd2ae9`;
- suíte: 440 testes aprovados;
- cobertura global: `86%` (mínimo 85%);
- blockers de QA/Security: nenhum.

## Decisão

`GO` técnico para a Fase 07 Integrations.

Este GO não equivale a aprovação humana da fase e não autoriza PR, merge, provider real, sandbox, callback público, credenciais, release, deploy ou Fase 08.

## PostgreSQL, migrations e regressão

O CI executou em PostgreSQL 17.11 desde banco vazio e aplicou `integrations.0001_initial` com sucesso. O rollback técnico para `integrations zero` e a reaplicação de `integrations.0001_initial` também passaram. `makemigrations --check --dry-run` retornou `No changes detected`.

A suíte completa executou 440 testes, todos aprovados, e a cobertura global ficou em 86%. Ruff, Django check, Docker build, Compose config e topologia Celery também passaram.

## Isolamento e autorização

Todas as entidades operacionais de Integrations permanecem Organization-scoped. Os testes revalidam rejeição de endpoint de outra Organization, circuit breaker isolado por conexão/Organization e visibilidade operacional sem vazamento de dados de outra Organization.

A configuração humana depende de Membership ativa: OWNER/ADMIN/MANAGER podem configurar e OPERATOR recebe somente visibilidade sanitizada. Membership inativa falha fechado.

## Concorrência, idempotência e retry

O teste concorrente PostgreSQL cria dois workers simultâneos tentando adquirir a mesma `IntegrationDelivery` e confirma exatamente um claim/attempt ativo. O domínio também mantém unicidade de idempotency key por Organization e unicidade da identidade de origem/endpoint/operação/versão.

Falhas transitórias possuem retry limitado a três tentativas com backoff. Falha permanente não é repetida. Lease expirado após início de envio torna a entrega `uncertain`, e aceitação ambígua/timeout também permanece `uncertain`, sem blind retry.

## Ingress, replay e autenticação

O contrato de ingress offline falha fechado quando `authenticated=False`, quando a versão do contrato diverge ou quando `occurred_at` sai da janela permitida. Event IDs são deduplicados por connection/endpoint, payload alterado para o mesmo event ID é rejeitado e eventos fora de ordem são registrados como evidência sanitizada.

Importante: `authenticated=True` nesta tranche representa somente o contrato provider-neutral/offline. Não há autenticação criptográfica de provider real ativada, e isso é correto porque callbacks públicos, sandbox, credenciais e providers reais estão explicitamente fora do escopo da Fase 07.

## Privacidade e secrets

O payload canônico usa allowlist estrita de chaves escalares e rejeita chaves arbitrárias ou objetos aninhados. Outbox e views não expõem o payload privado. Configuração da conexão rejeita metadata arbitrária e adapter não aprovado; `secret_alias` é apenas referência opaca.

Secret scan passou sem assinatura de secret real. Independence scan passou sem símbolos proibidos ou ligação ao Flowlog. Nenhum provider comercial ou efeito de rede externo foi introduzido.

## Reconciliação e degradação

Entregas `uncertain` são resolvidas por reconciliação idempotente. O circuit breaker degrada somente a `IntegrationConnection` correspondente após falhas consecutivas e não afeta conexões saudáveis de outra Organization.

## Infraestrutura de execução

As tasks de Integrations estão registradas no Celery e roteadas para a fila `integrations`. O gate de topologia confirmou que a agenda/rotas estão registradas e que Compose possui worker consumindo `default` e `integrations`.

Nenhum deploy ou alteração de infraestrutura externa foi executado.

## Riscos residuais não bloqueantes

1. `apps/integrations/tasks.py` possui cobertura direta de linhas baixa (35%), mas os serviços críticos e a topologia Celery são validados por testes e CI; manter acompanhamento ao adicionar novas tasks.
2. O reference adapter valida apenas arquitetura offline; não equivale a homologação de provider concreto.
3. O contrato de autenticação de ingress ainda não possui mecanismo criptográfico real, por desenho; qualquer provider/callback público requer checkpoint específico antes da ativação.
4. Inbound WhatsApp para conversas de vendas continua fora desta tranche genérica e exige escopo próprio futuro.

## Veredito

`GO`.

Não há blocker técnico de QA/Security para o candidato material `a2c1b1d90e9c331eb4f9bb1812a5e341d9e1a90e`.

Próximo checkpoint: aprovação humana final da Fase 07. Até essa decisão, a fase permanece candidata e PR, merge, release, deploy, providers reais, sandbox, callbacks públicos, credenciais e Fase 08 continuam não autorizados.
