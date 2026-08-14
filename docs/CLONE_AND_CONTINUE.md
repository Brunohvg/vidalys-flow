# Clonar e continuar o desenvolvimento

Este repositório contém código, migrations, decisões, estado, prompts e gates
necessários para outro desenvolvedor continuar a Vidalys Flow sem consultar o
Flowlog ou esta conversa.

## Clonagem

```bash
git clone https://github.com/Brunohvg/vidalys-flow.git
cd vidalys-flow
git fetch --all --prune
git switch main
git pull --ff-only
```

A branch `main` contém as fases aprovadas até Payments. O candidato da
Fase 06 está em `phase/06-messaging`, criada exatamente do SHA
`3e4fcfb064fbee350d3df131b2946974c8557098`; confira `project/state.json` e
`project/phases/06-messaging.json`. O plano está aprovado e a implementação
está em andamento. Não há provider, efeito externo, sandbox ou deploy autorizado.

## Ambiente local reproduzível

Requisitos: Git e Docker com Compose. Python 3.12, PostgreSQL 17, Redis,
Gunicorn, Celery e `uv` são fornecidos pelas imagens. Não use SQLite.

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
```

O Compose aguarda banco e Redis saudáveis, aplica migrations e inicia web,
worker e Beat na ordem correta. Assim, a máquina não precisa de banco, broker
ou runtime Python instalados fora do Docker.

Em WSL sem `systemd`, o Docker Engine local pode precisar ser iniciado após
abrir a distribuição:

```bash
sudo service docker start
docker info
```

Alternativamente, todo o gate pode rodar em containers:

```bash
docker compose -f docker-compose.test.yml up \
  --build --abort-on-container-exit --exit-code-from test
```

O banco local nasce vazio. Não copie dados, migrations, IDs, credenciais,
arquivos ou backups do Flowlog.

## Primeiro acesso local

Com web e dependências iniciados, crie uma organização de demonstração sem
passar senha na linha de comando:

```bash
docker compose up -d web worker-default worker-integrations beat
docker compose exec web .venv/bin/python manage.py bootstrap_organization \
  --organization-name "Minha empresa" \
  --slug "minha-empresa" \
  --owner-email "owner@example.com" \
  --owner-name "Nome do Owner" \
  --unit-name "Matriz"
docker compose exec web .venv/bin/python manage.py changepassword owner@example.com
```

Interfaces atuais:

- `/customers/`;
- `/products/`;
- `/orders/`;
- `/fulfillment/`;
- `/payments/` (aprovado, com providers externos desabilitados).
- `/messaging/` (candidato, providers externos desabilitados).

## Gate antes de entregar mudanças

```bash
uv run python scripts/agent_orchestrator.py validate-all
uv run python scripts/check_secrets.py
uv run python scripts/check_independence.py
uv run ruff check .
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run coverage run -m pytest
uv run coverage report
docker compose config
docker compose -f docker-compose.test.yml config
```

PostgreSQL 17 é obrigatório. O mínimo global de cobertura é 85%, mas regras
críticas precisam de testes comportamentais diretos mesmo quando o percentual
já foi atingido.

## Onde encontrar cada decisão

- estado oficial: `project/state.json`;
- última fase aprovada: `project/phases/05-payments.json`;
- fase candidata com segunda remediação, aguardando novo Review:
  `project/phases/06-messaging.json`;
- contratos aprovados: `docs/domains/FULFILLMENT.md` e
  `docs/domains/PAYMENTS.md`;
- ciclo de vida: `docs/decisions/ADR-012-FULFILLMENT-LIFECYCLE.md`;
- concorrência: `docs/decisions/ADR-013-FULFILLMENT-CONSISTENCY.md`;
- fluxo completo: `docs/SYSTEM_FLOW.md`;
- caminho até produção: `docs/ROADMAP_TO_PRODUCTION.md`;
- processo de agentes: `AGENTS.md` e `docs/agents/`;
- plano de Payments: `docs/domains/PAYMENTS_VISION.md`;
- contrato implementado de Payments: `docs/domains/PAYMENTS.md`;
- plano de Messaging: `docs/domains/MESSAGING_VISION.md`;
- contrato candidato de Messaging: `docs/domains/MESSAGING.md`;
- auditoria histórica isolada de Messaging/Evolution:
  `docs/domains/MESSAGING_FLOWLOG_REFERENCE_AUDIT.md`;
- código e testes: `apps/payments/` e `apps/messaging/`;
- evidência da Fase 5: `project/handoffs/phase-05.json`;
- incidente de recuperação:
  `project/incidents/phase-04-governance-recovery.md`.

## Continuação segura

Não pule checkpoints. O plano da Fase 06 já foi aprovado; P06-R01 a P06-R05
foram aceitos como resolvidos pelo Review 02 e a remediação de P06-R06 a
P06-R08 precisa de novo CI e Review independente. Depois seguem QA/Security,
handoff, aprovação humana final e autorização separada de PR/merge. Sandbox e
efeitos externos possuem checkpoints próprios.

Mercado Pago e Pagar.me pertencem ao contrato aprovado de Payments; Appmax vem
depois. Messaging propõe Evolution API linked-device, WhatsApp Cloud API
direta e Amazon SES, todos desligados.
Nenhum provider, contato, template, mensagem, webhook, credencial ou máquina
do Flowlog pode ser reutilizado. Homologação e máquina exclusiva de produção
pertencem à Fase 9; go-live pertence à Fase 10.
