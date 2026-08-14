# Review independente 03 — Fase 06 Messaging

- resultado: `APPROVED`;
- candidato material revisado: `cf871a561e529aa331479b13c792e6b2fcac6743`;
- carrier documental anterior observado: `4f6e5f2d57055a0b148956aa29662f73b6447056`;
- baseline (`actual_base_sha`): `3e4fcfb064fbee350d3df131b2946974c8557098`;
- dependency head aprovado: `3558ca30a5652be320feb3f28ab46a350ae9cad7`;
- CI material: run `31761251578`, `success` no SHA exato;
- CI carrier anterior: run `31761382119`, `success` no SHA exato;
- suíte no CI: 418 testes aprovados;
- evidência local registrada no handoff: 413 aprovados e 5 skips de governança dependentes de `.git`;
- testes diretos de Messaging: 138;
- cobertura registrada: `85.3952772073922%`;
- achados bloqueantes: nenhum.

## Escopo desta revisão

Este Review 03 revalida especificamente a segunda remediação da Fase 06 e os achados `P06-R06`, `P06-R07` e `P06-R08`, sem reimplementar ou alterar código. Também verifica se o delta reabre algum blocker previamente resolvido em `P06-R01` a `P06-R05`.

## Revalidação dos achados

### P06-R06 — resolvido

O contrato de evento agora separa explicitamente `event_contract_version` da versão do agregado. `enqueue_event` valida uma versão inteira positiva e a adiciona ao envelope sanitizado. O consumidor exige a versão exata aprovada por `SOURCE_EVENT_CONTRACT_VERSIONS` antes de resolver a fonte e filtra `MessageAutomationRule` pela mesma `event_version`.

A versão do agregado continua separada em `payload.version` e é usada para revalidar `source.version`. A regra não pode consumir envelope de versão divergente. Existem regressões para versão ausente, desconhecida e regra com versão diferente.

**Decisão:** resolvido.

### P06-R07 — resolvido

A criação e o uso de templates transacionais passaram a depender de um catálogo server-side fechado. `validate_transactional_template` exige correspondência exata de `semantic_key`, canal, locale, finalidade, corpo texto/HTML e schema de parâmetros.

A validação é aplicada na criação do template, no envio manual, no vínculo com automação e novamente antes do dispatch. Conteúdo promocional ou arbitrário não pode se tornar elegível apenas por estar ligado a um Order/Fulfillment/Payment.

**Decisão:** resolvido.

### P06-R08 — resolvido

A matriz comportamental passou a cobrir as seis fontes automáticas aprovadas:

- `order.confirmed`;
- `fulfillment.ready`;
- `fulfillment.dispatched`;
- `fulfillment.completed`;
- `payment.checkout_activated`;
- `payment.status_changed`.

A suíte também cobre versão de contrato ausente/desconhecida, versão de regra divergente, estado atual incompatível da fonte, replay/idempotência e conteúdo promocional fora do catálogo. O CI completo coletou e aprovou 418 testes.

**Decisão:** resolvido.

## Regressão dos blockers anteriores

Não surgiu evidência que reabra `P06-R01` a `P06-R05`:

- dispatch continua linearizado com leases e revalidação antes de I/O;
- snapshots de Message e templates usados continuam protegidos por guards ORM e PostgreSQL;
- regras permanecem versionadas, com conflito otimista e locks para mutação;
- falha transitória no consumo de source event continua retryable, enquanto rejeição de domínio gera receipt definitivo;
- isolamento por Organization, Membership, callback fail-closed e idempotência permanecem cobertos pela suíte completa.

## Segurança e efeitos externos

- Evolution, WhatsApp Cloud e SES permanecem atrás de adapters sem efeitos externos por padrão;
- CI não utilizou credenciais nem rede de provider;
- Evolution callback exige secret resolver, que permanece indisponível por design até canal de secrets aprovado;
- callbacks Meta e SES permanecem bloqueados enquanto autenticidade completa não estiver implementada/aprovada;
- callback possui limite de tamanho, validação de identificadores, rate limit Redis fail-closed e deduplicação;
- scanner de secrets e scanner de independência passaram;
- não há vínculo técnico com Flowlog; a consulta ao legado foi apenas read-only para ideias/failure modes no SHA congelado.

## Migrations, CI e runtime

O run `31761251578` executou com sucesso:

- validação de governança e baseline;
- testes do orquestrador;
- secret scan e independence scan;
- Ruff e Django check;
- migration consistency;
- aplicação desde PostgreSQL vazio;
- rollback técnico e reaplicação de Messaging;
- suíte de 418 testes;
- cobertura acima do gate de 85%;
- Docker build;
- Compose validation;
- topologia Celery `default`/`integrations`.

O run documental `31761382119` também terminou em `success` no carrier anterior.

## Achado não bloqueante

### P06-R09 — Baixa — handoff cita model de receipt inexistente

O handoff atual lista `messaging.MessageSourceEventReceipt` entre os models entregues, porém o código persistente usa `MessageCommandReceipt.source_event_id` com as operações `consume_source_event` e `consume_source_event_rejected` para evidência de consumo. Não foi encontrado model ou migration chamado `MessageSourceEventReceipt`.

**Impacto:** inconsistência documental; não altera o comportamento, a idempotência ou a segurança do candidato.

**Recomendação:** corrigir a lista de models do handoff antes do fechamento oficial da fase, sem criar um model novo apenas para satisfazer documentação.

## Riscos residuais não bloqueantes

- cobertura global está acima do gate por margem pequena;
- `apps.messaging.services` é grande e tem cobertura inferior à média global, embora os caminhos críticos possuam testes diretos;
- o teardown da base de testes ainda registra aviso conhecido de conexões concorrentes abertas, sem falha da suíte;
- Evolution linked-device continua não oficial e deve permanecer desabilitado até homologação específica;
- autenticidade/live callbacks, pairing, secrets reais, destinatários reais, sandbox, provider network e deploy continuam fora deste checkpoint.

## Conclusão

`APPROVED`.

`P06-R06`, `P06-R07` e `P06-R08` foram resolvidos no candidato material `cf871a561e529aa331479b13c792e6b2fcac6743`. Não há blocker de Review aberto. O achado `P06-R09` é documental e não bloqueia QA/Security, mas deve ser corrigido antes do fechamento oficial.

Este Review não aprova produto, não modifica `project/state.json`, não autoriza PR, merge, provider, sandbox, release, deploy nem Fase 07. O próximo checkpoint é QA/Security independente da Fase 06.