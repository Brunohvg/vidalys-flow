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

A branch `main` contém as fases aprovadas até Fulfillment. O plano aprovado e a
segunda remediação candidata de Payments estão em `phase/05-payments`; confira
`project/state.json` e `project/phases/05-payments.json`. Efeitos externos,
sandbox, PR, merge e deploy continuam sem autorização.

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
docker compose up -d web worker-default beat
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
- `/fulfillment/`.
- `/payments/` (somente na branch candidata da Fase 5).

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
- última fase aprovada: `project/phases/04-fulfillment.json`;
- fase em implementação candidata: `project/phases/05-payments.json`;
- contrato do domínio: `docs/domains/FULFILLMENT.md`;
- ciclo de vida: `docs/decisions/ADR-012-FULFILLMENT-LIFECYCLE.md`;
- concorrência: `docs/decisions/ADR-013-FULFILLMENT-CONSISTENCY.md`;
- fluxo completo: `docs/SYSTEM_FLOW.md`;
- caminho até produção: `docs/ROADMAP_TO_PRODUCTION.md`;
- processo de agentes: `AGENTS.md` e `docs/agents/`;
- plano de Payments: `docs/domains/PAYMENTS_VISION.md`;
- contrato implementado de Payments: `docs/domains/PAYMENTS.md`;
- código e testes: `apps/payments/`;
- evidência da Fase 4: `project/handoffs/phase-04.json`;
- incidente de recuperação:
  `project/incidents/phase-04-governance-recovery.md`.

## Continuação segura

Não pule checkpoints. O plano de Payments já foi aprovado e os Reviews 01, 02
e 03 pediram correções. A terceira remediação autorizada está na branch
exclusiva. O próximo fluxo é: commit material, CI no SHA material exato,
carrier contendo somente o handoff, Review 04 independente, QA/Segurança,
aprovação humana da fase e só então PR/merge se autorizados.

Mercado Pago e Pagar.me permanecem planejados para a Fase 5; Appmax vem
depois. Nenhum provider, webhook, credencial ou máquina do Flowlog pode ser
reutilizado. Homologação e máquina exclusiva de produção pertencem à Fase 9;
go-live pertence à Fase 10.
