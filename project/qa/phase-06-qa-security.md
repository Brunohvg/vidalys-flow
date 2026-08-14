# QA e Segurança — Fase 06 Messaging

- decisão técnica: `GO`;
- candidato material imutável: `cf871a561e529aa331479b13c792e6b2fcac6743`;
- Review independente 03: `APPROVED`;
- carrier do Review 03: `acdfa40e372456094f1508c41b33db98e4a2225e`;
- baseline (`actual_base_sha`): `3e4fcfb064fbee350d3df131b2946974c8557098`;
- dependency head aprovado: `3558ca30a5652be320feb3f28ab46a350ae9cad7`;
- CI material: run `31761251578`, `success` no SHA exato;
- CI documental da remediação anterior: run `31761382119`, `success`;
- suíte material no CI: 418 testes aprovados;
- testes diretos de Messaging registrados: 138;
- cobertura registrada: `85.3952772073922%`;
- blockers de QA/Security: nenhum.

## Decisão

`GO` técnico para a Fase 06 Messaging.

O candidato material passou pelos gates de governança, independência, secrets, lint, Django, migrations, rollback/reapply de Messaging, PostgreSQL, testes, cobertura, Docker, Compose e topologia Celery. O Review 03 revalidou como resolvidos `P06-R06`, `P06-R07` e `P06-R08`, sem reabrir `P06-R01` a `P06-R05`.

Este GO não equivale a aprovação humana de produto e não autoriza PR, merge, provider real, pairing real, callback público, sandbox, release, deploy ou Fase 07.

## Segurança de conteúdo e automação

- templates transacionais pertencem a catálogo server-side fechado;
- `semantic_key`, canal, locale, finalidade, corpo e schema precisam coincidir exatamente com o contrato aprovado;
- conteúdo promocional ou arbitrário é rejeitado na criação e volta a ser revalidado antes de envio/dispatch;
- automações consomem somente os seis eventos allowlisted e a versão exata do contrato;
- versão do contrato do evento e versão do agregado são evidências distintas;
- o consumidor revalida Organization, aggregate id, versão e estado atual da fonte antes de criar a mensagem;
- regras são filtradas por `event_version` e não podem consumir contrato divergente.

## Isolamento e autorização

A arquitetura permanece Organization-scoped. Services, selectors, workers, callbacks, canais, conexões, templates, preferências, regras, mensagens, attempts e receipts trabalham com Organization explícita. Membership ativa continua sendo requisito para comandos humanos. Não foi observada dependência de Tenant ou runtime legado.

Messaging não altera estados canônicos de Orders, Fulfillment ou Payments; apenas consome eventos e revalida as fontes.

## Idempotência, concorrência e retry

- `MessageCommandReceipt` protege comandos e consumo de eventos;
- source-event replay não duplica mensagens;
- um único attempt ativo por Message é protegido por constraint PostgreSQL;
- leases e pessimistic locks serializam dispatch;
- falha transitória de infraestrutura não é marcada como rejeição permanente e permanece retryable;
- falhas de domínio conhecidas geram receipt de rejeição e não entram em loop infinito;
- worker perdido após início do envio move o attempt/message para `uncertain` em vez de repetir cegamente o transporte.

## Providers e efeitos externos

Evolution API, WhatsApp Cloud e Amazon SES estão representados por contratos provider-neutral/offline. Os adapters permanecem desabilitados para efeitos externos por padrão.

- nenhum secret real foi introduzido;
- nenhum provider network foi usado no CI;
- pairing, destinatários reais e envio real permanecem fora do checkpoint;
- Evolution callback depende de secret resolver ainda não provisionado e falha fechado;
- callbacks de providers sem autenticidade completa aprovada permanecem bloqueados;
- URL de Evolution possui HTTPS/allowlist/SSRF guards no contrato antes de futura ativação.

## Callback hardening

O callback implementado possui:

- limite de payload de 64 KiB;
- validação fechada de identificadores;
- digest do corpo em vez de persistência do callback bruto;
- rate limiting Redis fail-closed;
- replay/deduplicação por evidência autenticada;
- Organization derivada do canal/conexão e não de parâmetro livre do payload;
- mapeamento canônico separado do estado do provider.

Quando autenticidade completa não existe, o comportamento é bloquear, não aproximar.

## Privacidade

O contrato evita persistir raw provider request/response, corpo recebido, credenciais, tokens, assinaturas, documentos, endereços ou diagnósticos arbitrários em AuditEvent/Outbox/receipts. Destination e demais evidências pessoais seguem as regras de masking previstas por papel.

## Migrations, regressão e CI

O CI `31761251578` executou no material `cf871a...`:

- 418 testes aprovados;
- PostgreSQL 17;
- migrations desde banco vazio;
- rollback técnico e reaplicação de Messaging;
- secret scan;
- independence scan;
- Ruff;
- Django check;
- migration consistency;
- Docker build;
- Compose validation;
- Celery runtime topology.

A cobertura registrada de `85.3952772073922%` supera o gate mínimo de 85%.

## Riscos residuais não bloqueantes

1. A cobertura global está apenas moderadamente acima do mínimo; crescimento futuro deve acrescentar testes antes de código adicional.
2. `apps.messaging.services` concentra muita lógica; continuar priorizando testes comportamentais e futura decomposição quando houver pressão real de manutenção.
3. Existe aviso conhecido de teardown do banco de testes com conexões concorrentes ainda abertas; não alterou o resultado da suíte, mas deve continuar sendo acompanhado.
4. Evolution linked-device é não oficial e deve permanecer desabilitado até homologação específica.
5. Callbacks Meta/SES e outros efeitos externos continuam bloqueados enquanto contratos de autenticidade e secret channels não forem aprovados.
6. O handoff lista `messaging.MessageSourceEventReceipt`, mas a implementação usa `MessageCommandReceipt.source_event_id`; corrigir essa inconsistência documental antes do fechamento oficial, sem criar model desnecessário.

## Veredito

`GO`.

Não há blocker técnico de QA/Security para o candidato material `cf871a561e529aa331479b13c792e6b2fcac6743`.

Próximo checkpoint: decisão humana final sobre a Fase 06. Até essa decisão, a fase permanece candidata; PR, merge, release, deploy, providers reais e Fase 07 continuam não autorizados.