# QA e Segurança — Fase 05 Payments

- decisão técnica: `NO-GO`;
- checkpoint: QA/Segurança independente, sem correção de código e sem
  aprovação de produto;
- branch: `phase/05-payments`;
- candidato material imutável:
  `464c2ac9af1bbeaacf0f33cccec7af5a73feb94e`;
- carrier de Review 04 observado:
  `b4222299d92901654657d101e98c44d31e17754c`;
- baseline (`actual_base_sha`):
  `4fd3a9259e9e2f31acdab44f13499eade79ab59e`;
- dependência aprovada:
  `888685886d7a17c6eeb008674be86656e4f6fa40`;
- Review 04: `APPROVED`, sem blocker de código identificado naquele
  checkpoint;
- blockers de QA: `P05-Q01` e `P05-Q02`.

## Decisão

`NO-GO`. O núcleo de domínio, os controles de segurança, as migrations e as
suítes automatizadas passaram, mas o runtime versionado não consegue executar
o fluxo assíncrono central de Payments. O Beat publica tasks de Payments que
não são descobertas pelo aplicativo Celery e não existe worker consumindo a
fila `integrations` para a qual criação e cancelamento de checkout são
roteados.

Este parecer não corrige os achados, não reprova o produto e não autoriza
sandbox, provider, PR, merge, release, deploy, mudança em
`project/state.json` ou fase posterior.

## Achados bloqueantes

### P05-Q01 — crítico — tasks de Payments não são registradas no runtime Celery

`config/celery.py` fornece uma lista explícita para `autodiscover_tasks`, mas
essa lista não contém `apps.payments`. A configuração do Beat agenda:

- `apps.payments.tasks.consume_order_cancellations`;
- `apps.payments.tasks.dispatch_checkout_requests`;
- `apps.payments.tasks.dispatch_checkout_cancellations`.

Após rebuild dos serviços no SHA candidato, o worker registrou somente:

- `apps.fulfillment.tasks.consume_order_cancellations`;
- `apps.platform.tasks.publish_pending_outbox`;
- `apps.platform.tasks.record_beat_heartbeat`.

Nenhuma task de Payments apareceu em `celery inspect registered`. Assim, até
o consumer de cancelamento de Order roteado para `default` é desconhecido pelo
worker e mensagens entregues a ele serão rejeitadas como task não registrada.
Criação e cancelamento de checkout não podem ser executados pelo runtime
declarado.

### P05-Q02 — alto — a fila `integrations` não possui consumidor no Compose

`CELERY_TASK_ROUTES` envia `dispatch_checkout_requests` e
`dispatch_checkout_cancellations` para `integrations`. O `docker-compose.yml`
declara somente `worker-default`, iniciado com `--queues=default`. Não existe
serviço de worker para `integrations`.

O `docker compose config --services` retornou apenas `db`, `redis`, `migrate`,
`web`, `worker-default` e `beat`. Após rebuild, `celery inspect active_queues`
confirmou exclusivamente a fila `default`. Mesmo que P05-Q01 fosse removido
isoladamente, os dois comandos de provider continuariam acumulados sem
consumidor.

O CI atual não detecta os dois problemas: ele valida build e sintaxe do
Compose, mas não sobe o worker para verificar tasks registradas, filas ativas
e correspondência entre Beat, routes e consumers.

## Achado não bloqueante

### P05-Q03 — baixo — documentação temporal anterior ao Review 04

O cabeçalho de `docs/domains/PAYMENTS.md` ainda afirma que a terceira
remediação aguarda validação e nova revisão independente. O cabeçalho de
`docs/domains/PAYMENTS_VISION.md` afirma que ela aguarda Review 04. O Review 04
já foi concluído e aprovado no carrier
`b4222299d92901654657d101e98c44d31e17754c`.

O conteúdo normativo e a ideia central continuam coerentes; o defeito é
temporal. Ele deverá ser corrigido na remediação autorizada, sem reclassificar
este QA como aprovação.

## Git, ancestralidade e fronteira

- `dependency_head` é ancestral da baseline;
- a baseline é ancestral do candidato material;
- o candidato material é ancestral do carrier de Review 04;
- os commits do intervalo são lineares, sem merge commit;
- `464c2ac..b422229` altera somente o handoff, o manifesto e o relatório de
  Review 04;
- a árvore estava limpa antes da criação deste relatório;
- `origin/main` permaneceu em
  `4fd3a9259e9e2f31acdab44f13499eade79ab59e`;
- nenhum código foi alterado neste checkpoint.

## CI no SHA exato

- candidato material: run `31556138368`, `success`, SHA
  `464c2ac9af1bbeaacf0f33cccec7af5a73feb94e`;
- carrier do handoff: run `31556315913`, `success`, SHA
  `7c9ec3ec12f1da482b57ad654a86751a81ce69c5`;
- carrier do Review 04: run `31556713278`, `success`, SHA
  `b4222299d92901654657d101e98c44d31e17754c`.

Os três runs concluíram governança, scanners, Ruff, Django, migrations,
testes, cobertura, Docker build e validação de Compose. O run material registrou
275 testes aprovados, nenhum skip e cobertura total arredondada de 85%. A
medição independente do Review 04 foi 85,23629489603024%, acima do mínimo de
85%.

## PostgreSQL, testes e qualidade

- Compose de teste iniciado com PostgreSQL 17.10 e Redis efêmeros;
- todas as migrations aplicadas desde banco vazio;
- Payments revertido até zero e reaplicado até
  `0004_paymentattempt_cancellation_correlation`;
- suíte no container: 270 aprovados e cinco testes de governança ignorados
  porque a imagem deliberadamente não contém `.git`;
- CI material com checkout Git completo: 275 aprovados e zero skips;
- Payments direto neste checkpoint: 68 aprovados;
- cobertura total: acima do gate de 85%;
- Ruff, Django check, migration consistency, Docker build e ambos os Compose:
  aprovados;
- validação JSON, estado, roadmap, manifestos, handoffs, templates e baseline:
  aprovada;
- `git diff --check`: aprovado.

Os testes diretos cobrem locks PostgreSQL e concorrência em criação do intent,
tentativa única, dispatch, cancelamento, callback e cancelamento de Order;
idempotência, conflito de payload e `expected_version`; estados regressivos e
respostas autoritativas; correlação exata de cancelamento; callback concorrente
e isolamento de falha por item.

## Isolamento, autorização e privacidade

- services, selectors, workers e callbacks escopam Organization e revalidam
  entidades relacionadas;
- comandos humanos exigem Membership ativa de manager tier;
- admin financeiro read-only exige Organization ativa e OWNER, ADMIN ou
  MANAGER, negando OPERATOR, membership inativa e objeto cross-tenant;
- OPERATOR recebe nome mascarado e não recebe IDs externos, conta do provider
  ou código de atenção, mas pode copiar apenas link ativo;
- testes cross-Organization, cross-account e Membership passaram;
- snapshots financeiros são imutáveis no ORM, `update`, `bulk_update` e
  trigger PostgreSQL;
- AuditEvent e OutboxEvent usam schemas fechados e flags canônicas;
- callback bruto, headers, assinatura, token, credencial, URL hospedada, PII,
  diagnóstico externo e texto livre não foram observados em audit, outbox,
  receipts ou logs;
- receipts guardam hashes/IDs sanitizados e não guardam payload de comando ou
  corpo do callback.

## Callbacks e providers

- Mercado Pago exige JSON limitado a 64 KiB, identificadores com allowlist,
  `X-Signature`, `X-Request-Id`, janela de cinco minutos, comparação HMAC em
  tempo constante, replay key autenticada, conta interna e re-fetch
  autoritativo;
- deduplicação ocorre antes de novo fetch para replay conhecido;
- o rate limiter usa chave derivada por hash de conta e origem e falha
  fechado quando Redis não está disponível;
- divergência de conta, recurso, valor ou moeda não confirma pagamento;
- callback Pagar.me permanece bloqueado por aplicação e constraint
  PostgreSQL;
- adapters reais herdam bloqueio de efeitos e a suíte bloqueia resolução DNS
  dos hosts conhecidos de Mercado Pago e Pagar.me;
- nenhum secret, provider, sandbox, webhook público, cobrança real, Flowlog ou
  deploy foi acessado.

## Docker, Compose, Celery e Beat

- Docker build: aprovado;
- Compose principal e de teste: sintaticamente válidos;
- PostgreSQL e Redis: saudáveis durante os testes;
- migrations no serviço `migrate`: aprovadas;
- Beat: iniciou e carregou a agenda de Payments;
- worker reconstruído: saudável, mas somente na fila `default` e sem qualquer
  task de Payments registrada;
- resultado operacional: reprovado por P05-Q01 e P05-Q02.

Os containers efêmeros de teste e os serviços `migrate`, `worker-default` e
`beat` iniciados para QA foram removidos ao final. Os serviços locais
preexistentes de PostgreSQL e Redis permaneceram intactos.

## Riscos residuais e escopo preservado

- cobertura acima do mínimo por margem estreita;
- o rate limiter depende de Redis e falha fechado;
- Pagar.me callback continua sem contrato de autenticidade aprovado e deve
  permanecer bloqueado;
- fixtures de provider devem ser revalidadas antes de qualquer sandbox;
- observabilidade, credenciais, sandbox, registro público de webhook,
  provider real, homologação e deploy permanecem posteriores;
- Appmax, Flowlog, partial/split/multi-currency, refund, disputa, chargeback,
  taxa, juros, settlement, receivables, Messaging e fases posteriores
  permanecem fora do escopo.

## Próximo caminho seguro

Uma remediação humana separadamente autorizada deve registrar as tasks de
Payments no aplicativo Celery, prover um consumer explícito para
`integrations`, adicionar um gate executável que compare agenda/routes com
tasks e filas do runtime, e corrigir o status temporal da documentação. Depois
disso são necessários novo Review independente e nova execução completa de
QA/Segurança. Até lá, a Fase 05 permanece candidata e tecnicamente bloqueada.
