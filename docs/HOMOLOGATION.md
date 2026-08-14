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
