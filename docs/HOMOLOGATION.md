# Homologação — Vidalys Flow

Este documento define o procedimento da Fase 09. Ele não autoriza produção, go-live, cutover, provider real, sandbox ou callback público.

## Topologia Coolify

A homologação usa dois recursos principais:

1. PostgreSQL 17 como database resource separado, vazio, exclusivo da Vidalys Flow e sem porta pública;
2. uma aplicação Docker Compose baseada em `docker-compose.homologation.yml` contendo `web`, `worker-default`, `worker-integrations`, `beat`, `release` e `redis`.

Somente `web:8000` recebe ingress pelo proxy do Coolify. Redis e os processos Celery não expõem portas públicas. O PostgreSQL é alcançado somente por `DATABASE_URL` através do caminho privado disponibilizado pelo ambiente.

Nenhum banco, Redis, volume, secret, usuário, domínio, runtime ou infraestrutura do Flowlog pode ser reutilizado.

## Configuração

Cadastre no Coolify as variáveis descritas em `.env.homologation.example`. Valores reais permanecem exclusivamente no secret store/runtime do ambiente.

Obrigatórias:

- `SECRET_KEY`;
- `DATABASE_URL`;
- `ALLOWED_HOSTS`;
- `CSRF_TRUSTED_ORIGINS`.

A homologação base mantém `VIDALYS_DEMO_MODE=1`, preservando o bloqueio de efeitos externos. Alterar esse valor não é parte da implantação base e exige autorização separada para o provider específico.

## Release e migrations

O serviço `release` é temporário e executa somente:

```text
python manage.py migrate --noinput
```

`web`, workers e Beat dependem da conclusão bem-sucedida desse serviço. Falha de migration deve bloquear a inicialização do runtime novo; não ignore nem marque migrations como fake.

A primeira homologação deve apontar para um PostgreSQL 17 vazio. Todas as migrations devem ser aplicadas desde zero.

## Healthchecks

- liveness: `/health/live/`;
- readiness: `/health/ready/`;
- Redis: `redis-cli ping`;
- workers: Celery inspect/ping;
- Beat: processo principal validado pelo healthcheck do Compose.

O proxy termina TLS. O healthcheck interno do container deve informar `X-Forwarded-Proto: https` para que `SECURE_SSL_REDIRECT` não converta a chamada interna em redirecionamento HTTPS para `127.0.0.1`.

## Bootstrap

Depois de migrations e readiness:

1. executar somente o bootstrap aprovado pelo projeto;
2. criar credenciais administrativas por canal seguro;
3. confirmar Membership/Organization antes de qualquer teste funcional;
4. nunca registrar senha, token ou secret em issue, CI, log ou handoff.

## Smoke/acceptance

Antes de Review, registrar evidência de:

- `/health/live/` e `/health/ready/` saudáveis;
- login e seleção de Organization;
- Customers/Products;
- Orders;
- Fulfillment;
- Payments com provider bloqueado;
- Messaging com provider bloqueado;
- Integrations com efeitos externos bloqueados;
- Dashboard;
- workers `default` e `integrations` consumindo somente suas filas previstas;
- Beat ativo;
- isolamento cross-Organization preservado.

## Backup e restore

O PostgreSQL separado deve possuir backup próprio no Coolify ou mecanismo externo aprovado. Antes da aprovação final da Fase 09:

1. criar um backup de homologação;
2. registrar horário, versão da aplicação e versão PostgreSQL, sem secrets;
3. restaurar em database vazio/temporário exclusivo;
4. executar `python manage.py migrate --noinput` após o restore para confirmar compatibilidade;
5. executar health/readiness e smoke mínimo;
6. destruir o recurso temporário conforme a política operacional aprovada.

A evidência deve comprovar restore real; a mera existência de configuração de backup não é suficiente.

## Rollback

Rollback de aplicação significa retornar ao commit/imagem anteriormente aprovada sem reusar runtime do Flowlog. Antes de reverter, classifique migrations do release:

- se apenas compatíveis/forward-safe, voltar a imagem conforme runbook;
- se houver migration que exija reversão, executar o rollback técnico previamente testado e somente após backup;
- nunca usar `--fake` como mecanismo de recuperação.

Fase 10 somente poderá usar um procedimento de rollback comprovado na homologação.

## Resposta a incidentes

Qualquer falha que comprometa disponibilidade, integridade, isolamento entre Organizations, confidencialidade, migrations, filas, autenticação, backup/restore ou comportamento fail-closed deve ser tratada como incidente operacional de homologação. A prioridade é preservar dados e evidências e impedir ampliação do impacto; restaurar rapidamente o serviço nunca justifica ignorar os guardrails do projeto.

### 1. Classificação e abertura

Ao detectar um incidente, registre um identificador e classifique a severidade sem incluir secrets, cookies, tokens ou payloads privados completos:

- **SEV-1 — crítico:** suspeita de vazamento cross-Organization, exposição de credencial/secret, corrupção/perda de dados, PostgreSQL indevidamente público, efeito externo não autorizado ou falha de restore que comprometa recuperação;
- **SEV-2 — alto:** indisponibilidade persistente de `web`, PostgreSQL, Redis ou workers; migration/release quebrado; fila crítica parada/acumulando; autenticação/autorização degradada;
- **SEV-3 — moderado:** degradação parcial sem perda de isolamento/integridade, alerta operacional recorrente ou falha recuperável sem impacto em dados canônicos.

O registro mínimo deve conter horário UTC, SHA/imagem em execução, recurso afetado, sintomas, severidade, Organization(s) potencialmente afetada(s), ações já executadas e responsável pela condução. Se a extensão do impacto for desconhecida, trate pela severidade mais alta plausível até descartá-la.

### 2. Contenção imediata

Antes de tentar correções amplas:

1. interrompa novos deploys e migrations;
2. mantenha `VIDALYS_DEMO_MODE=1` e não habilite provider, sandbox ou callback como forma de diagnóstico;
3. para suspeita de efeito externo ou vazamento, desative o componente/rota/worker afetado e revogue/rotacione a credencial comprometida pelo canal seguro apropriado;
4. para suspeita de cross-Organization, suspenda o fluxo afetado e preserve os registros necessários para determinar origem e alcance;
5. para falha de banco, não recrie, não faça `flush`, não use `--fake` e não aplique comandos destrutivos antes de snapshot/backup quando isso ainda for seguro;
6. isole o recurso comprometido sem conectar ou reutilizar qualquer runtime, banco, Redis ou secret do Flowlog.

Se a contenção exigir indisponibilidade temporária da homologação, indisponibilidade é preferível a operar com integridade ou isolamento incertos.

### 3. Preservação de evidências

Antes de reinícios destrutivos, limpeza ou rollback, preserve somente o necessário para investigação:

- SHA/imagem e configuração não secreta efetivamente implantados;
- status e timestamps de `web`, workers, Beat, Redis e PostgreSQL;
- resultado de `/health/live/` e `/health/ready/`;
- logs sanitizados do intervalo do incidente;
- estado das filas e erros de tasks relevantes;
- status do release/migration e tabela de migrations aplicada quando pertinente;
- metadados de backup/restore, sem conteúdo sensível desnecessário.

Não copie para tickets/handoffs tokens, senhas, cookies, chaves, connection strings completas, payloads brutos de provider ou PII não necessária. Evidências sensíveis devem permanecer no mecanismo seguro autorizado para o ambiente.

### 4. Diagnóstico e decisão de recuperação

Determine primeiro qual camada falhou: aplicação, release/migration, PostgreSQL, Redis, worker/Beat, proxy/TLS, configuração ou integração. Depois escolha explicitamente uma das estratégias:

- **corrigir à frente:** somente quando a causa estiver identificada, a mudança for mínima/revisável e não exigir alterar dados canônicos de forma insegura;
- **rollback da aplicação:** retornar à última imagem/SHA aprovado quando o runtime novo for a causa e as migrations forem compatíveis com a versão anterior;
- **rollback técnico de migration:** somente para migration previamente considerada reversível/testada, após backup e avaliação de perda de dados;
- **restore do PostgreSQL:** quando houver corrupção/perda que não possa ser resolvida de forma segura, usando backup comprovado e um database exclusivo da Vidalys Flow.

Não execute rollback de imagem se o schema atual for incompatível com a versão anterior. Não use `--fake`, edição manual do histórico de migrations ou reaproveitamento do Flowlog como mecanismo de recuperação.

Incidentes SEV-1 exigem decisão humana explícita antes de reabilitar o fluxo afetado. Qualquer incidente que envolva provider/credencial continua submetido ao subgate específico e não transforma homologação em autorização para I/O externo.

### 5. Recuperação controlada

Após aplicar a ação escolhida:

1. confirme PostgreSQL disponível e schema/migrations no estado esperado;
2. confirme Redis saudável;
3. execute o serviço `release` apenas se a estratégia exigir e valide conclusão com sucesso;
4. suba/valide `web`, `worker-default`, `worker-integrations` e `beat` na topologia aprovada;
5. valide `/health/live/` e `/health/ready/`;
6. execute smoke mínimo de login, Organization, operações de leitura/escrita permitidas e Dashboard;
7. valide workers nas filas `default` e `integrations` e Beat ativo;
8. execute verificação cross-Organization adequada ao componente afetado;
9. confirme que Payments, Messaging e Integrations permanecem sem efeitos externos não autorizados;
10. se houve restore, execute a sequência de validação de restore definida neste runbook antes de considerar o ambiente recuperado.

Não declare recuperação somente porque os containers estão `running`; readiness e smoke devem passar.

### 6. Validação pós-incidente e encerramento

Antes de encerrar:

- confirme que o sintoma original não é reproduzível no caminho validado;
- confirme ausência de nova exposição pública de PostgreSQL/Redis/Celery;
- confirme isolamento de Organization e autenticação/autorização quando aplicável;
- confirme que logs e evidências ficaram sanitizados;
- registre causa raiz conhecida ou hipótese ainda aberta;
- registre ações corretivas e preventivas, incluindo testes/documentação adicionais necessários;
- anexe as evidências de CI, smoke, restore ou rollback relevantes sem secrets.

Se a causa raiz continuar desconhecida em SEV-1/SEV-2, o incidente não deve ser considerado definitivamente encerrado; o ambiente pode permanecer bloqueado para o fluxo afetado até nova decisão.

### 7. Escalonamento e efeitos na governança

- **SEV-1:** interrompe o checkpoint da Fase 09 para o fluxo afetado, exige registro imediato e decisão humana antes de retomada; suspeita de segurança deve ser encaminhada ao checkpoint de QA/Security/segurança apropriado.
- **SEV-2:** bloqueia promoção/aprovação até recuperação validada e registro da causa/mitigação.
- **SEV-3:** pode ser tratado no ciclo normal desde que não esconda risco de segurança, dados ou tenancy.

Todo incidente material deve registrar impacto na candidata/artefatos da fase. Se a correção alterar runtime, configuração material ou segurança, ela gera nova candidata/evidência de CI e exige revalidação pelos checkpoints aplicáveis. Nenhum incidente autoriza PR/merge, produção, go-live, cutover ou início da Fase 10.

## Observabilidade

A homologação deve permitir observar, no mínimo:

- estado de `web`, workers, Beat e Redis;
- health/readiness;
- falhas de migrations/release;
- fila Celery acumulada/degradada;
- erros Django/Celery sanitizados;
- disponibilidade do PostgreSQL;
- resultado dos backups.

Logs e alertas não podem carregar credentials, cookies, tokens, payloads brutos de provider ou snapshots privados completos.

## Providers

A homologação base não ativa providers. Cada provider exige subgate explícito contendo, no mínimo:

- autorização humana específica;
- credencial exclusiva da Vidalys Flow;
- sandbox/endpoint aprovado;
- autenticação de callback comprovada quando aplicável;
- timeout/retry/idempotência/deduplicação/reconciliação;
- sanitização de logs e payloads;
- evidência de teste;
- plano de desligamento/rollback.

Sem esse subgate, `VIDALYS_DEMO_MODE` permanece bloqueando I/O externo.

## Critério de conclusão

A Fase 09 somente pode avançar para Independent Review depois de CI verde no SHA material, documentação consistente e evidência de que a topologia homologação é renderizável. Provisionamento externo real, quando autorizado, deve ser registrado separadamente e nunca inferido apenas pelo conteúdo deste repositório.
