# QA e Segurança — Fase 09 Infrastructure and homologation

- decisão técnica: `GO`;
- candidata material imutável: `fac5e9c0d86b2137c8542d7ef4101e1746a38fab`;
- carrier de governança/review validado: `c54dc7aa483d8cd112b70ebe4651997af5fcd034`;
- baseline (`actual_base_sha`): `12b519c3e8237e1ebe43c1a0253b0747e0680e07`;
- dependency head aprovado da Fase 08: `8ec559ab69b88fbd781144b1ad9dc00d465193c2`;
- Independent Review: `READY_FOR_QA_AND_SECURITY`, sem finding bloqueante;
- Foundation CI material: #209 / run `31849693025`, `success` no SHA material exato;
- Foundation CI carrier final de review: #214 / run `31854668875`, `success` no SHA `c54dc7aa483d8cd112b70ebe4651997af5fcd034`;
- suíte material: 454 testes aprovados, 0 skipped;
- cobertura global: `86%` (mínimo 85%);
- PostgreSQL de CI: `17.11`;
- blockers de QA/Security: nenhum.

## Decisão

`GO` técnico para a Fase 09 — Infrastructure and homologation.

Este GO não equivale a aprovação humana e não autoriza PR, merge, deploy no Coolify, criação de banco/DNS, provider, sandbox, credenciais, callback público, produção/go-live, cutover, Flowlog shutdown, importação legada ou Fase 10.

## Escopo material e carrier

A comparação da base real `12b519c3e8237e1ebe43c1a0253b0747e0680e07` até a candidata material introduz somente artefatos de infraestrutura/homologação, documentação e governança/test fixture necessários à Fase 09; não introduz model, migration ou lifecycle de negócio. A comparação de `fac5e9c0d86b2137c8542d7ef4101e1746a38fab` até `c54dc7aa483d8cd112b70ebe4651997af5fcd034` é cinco commits à frente e altera apenas `project/handoffs/phase-09.json`, `project/phases/09-infrastructure-homologation.json` e `project/reviews/phase-09-review-report.json`. O carrier não redefine a candidata material.

## PostgreSQL e Redis

`docker-compose.homologation.yml` não contém serviço PostgreSQL. O PostgreSQL 17 é um recurso separado, exclusivo da Vidalys Flow, acessado somente por `DATABASE_URL`; a topologia documentada exige conectividade privada e nenhuma publicação de 5432. A validação do ambiente real continua pendente até provisionamento autorizado.

Redis permanece dentro da stack como broker/cache não canônico, sem `ports` publicados e configurado sem persistência (`--save "" --appendonly no`). Estado canônico permanece exclusivamente no PostgreSQL.

## Ingress e topologia Celery

Somente `web` declara `expose: 8000` no Compose de homologação. Redis, `worker-default`, `worker-integrations`, Beat e `release` não publicam portas. O runtime Celery separa `worker-default` em `default` e `worker-integrations` em `integrations`; o gate `scripts/check_celery_runtime.py` confirmou agenda/routes e consumo das duas filas. Existe um único serviço Beat.

O comportamento efetivo do proxy/ingress do Coolify permanece dependente do ambiente real e não foi falsamente considerado provado por CI.

## Release e migrations

O serviço `release` é one-shot (`restart: "no"`) e executa somente `.venv/bin/python manage.py migrate --noinput`. `web`, ambos os workers e Beat dependem de `release` com `condition: service_completed_successfully`, portanto falha de migration impede inicialização do runtime novo no contrato Compose.

`DATABASE_URL` é obrigatório tanto no Compose (`${DATABASE_URL:?DATABASE_URL is required}`) quanto em `config.settings.production`; não existe fallback SQLite ou banco local perigoso. A Fase 09 introduz zero migration e zero model.

## Settings de produção e segurança HTTP

A homologação usa `config.settings.production`. Foi verificado diretamente:

- `DEBUG = False`;
- `SESSION_COOKIE_SECURE = True`;
- `CSRF_COOKIE_SECURE = True`;
- `SECURE_SSL_REDIRECT = True`;
- HSTS de 1 ano, includeSubDomains e preload;
- `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`;
- `ALLOWED_HOSTS` e `CSRF_TRUSTED_ORIGINS` obrigatórios;
- CORS não é wildcard e o exemplo usa somente a origem HTTPS da homologação.

O readiness interno de `web` usa HTTP local com `X-Forwarded-Proto: https`, evitando redirect indevido sob TLS terminado no proxy. O healthcheck específico do serviço em Compose substitui o healthcheck genérico da imagem para a topologia de homologação.

## Fail-closed e I/O externo

A homologação base fixa `VIDALYS_DEMO_MODE=1` no exemplo e usa default `1` no Compose. `production.py` também tem default booleano fail-closed. O guardrail global bloqueia efeitos externos quando o modo demo está ativo.

Payments continua com adapters desabilitados que lançam `ProviderEffectsDisabled`; Messaging mantém adapters desabilitados e `require_network_allowed()` consulta o guardrail; Integrations mantém somente `ReferenceAdapter` determinístico e offline. Não foi ativado provider, sandbox, credencial real, callback público ou I/O externo.

## Secrets e independência do Flowlog

`.env.homologation.example` contém somente placeholders (`REPLACE_*`, domínio `.invalid`) e nenhuma credencial real. Foundation CI #209 passou `check_secrets.py` e `check_independence.py`.

Nenhum banco, Redis, runtime, secret, identidade/tenancy, código ou infraestrutura do Flowlog é reutilizado. A candidata não adiciona ligação operacional com Flowlog.

## Organization, autenticação e autorização

A Fase 09 não altera código de domínio, autenticação, Membership ou selectors/policies de tenancy. A suíte completa das fases aprovadas passou novamente com 454 testes, incluindo regressões cross-Organization e autenticação/autorização. Não foi identificado novo caminho de seleção arbitrária de Organization ou bypass introduzido pela infraestrutura.

## CI e quality gates

Na candidata material exata `fac5e9c0d86b2137c8542d7ef4101e1746a38fab`, Foundation CI #209 / run `31849693025` concluiu `success` e confirmou:

- governance JSON/state/roadmap/manifests/handoffs/templates;
- approved-phase ancestry e baseline;
- orchestrator tests;
- secret scan;
- independence scan;
- Ruff;
- Django check;
- `makemigrations --check --dry-run` com `No changes detected`;
- aplicação completa das migrations em PostgreSQL 17.11 vazio;
- rollback/reapply de Fulfillment, Payments, Messaging e Integrations;
- 454/454 testes, 0 skipped;
- cobertura total 86%;
- Docker build;
- Compose local, test e homologation;
- topologia Celery `default, integrations`.

Foundation CI #214 / run `31854668875` também concluiu `success` no carrier final `c54dc7aa483d8cd112b70ebe4651997af5fcd034`.

## Runbook e P09-IR-001

`docs/HOMOLOGATION.md` cobre topologia, configuração, release/migrations, healthchecks, bootstrap, smoke, backup/restore, rollback, observabilidade, providers e resposta a incidentes.

`P09-IR-001` permanece `RESOLVED / PASS`: o procedimento de incident response cobre classificação SEV-1/2/3, contenção, preservação de evidências, diagnóstico e decisão de recuperação/rollback, recuperação controlada, validação pós-incidente, escalonamento e impacto na governança.

## Riscos residuais e deferred

1. Restore real ainda **não está provado**. A documentação exige backup e restore em database temporário exclusivo, migrations, readiness e smoke; isso deve produzir evidência no ambiente real antes da aprovação final da Fase 09.
2. Private networking real do PostgreSQL e ausência de exposição pública de 5432 dependem da configuração efetiva do recurso no Coolify.
3. O comportamento real de ingress/proxy/TLS e healthchecks no Coolify depende do ambiente real.
4. Execução real do runbook de incident response permanece dependente de ambiente autorizado.
5. Warning de depreciação Node.js 20 em Actions permanece não bloqueante enquanto os actions são executados sob Node.js 24.

Esses itens permanecem riscos/deferred explícitos e não foram promovidos artificialmente a evidência comprovada.

## Veredito

`GO`.

Não há finding bloqueante de QA/Security para a candidata material `fac5e9c0d86b2137c8542d7ef4101e1746a38fab`.

`P09-IR-001`: `RESOLVED / PASS`.

A Fase 09 deve permanecer `candidate`, com `human_approval_status: pending`. O próximo checkpoint permitido é exclusivamente decisão humana final da Fase 09. Nenhum deploy, PR, merge, produção/go-live, provider, sandbox, credencial, callback, cutover ou Fase 10 é autorizado por este GO.