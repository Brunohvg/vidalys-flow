# Clonar e continuar o desenvolvimento

Este repositório contém código, migrations, decisões, estado, prompts e gates
necessários para outro desenvolvedor continuar a Vidalys Flow sem consultar o
Flowlog ou esta conversa.

## Clonagem

```bash
git clone https://github.com/Brunohvg/vidalys-flow.git
cd vidalys-flow
git fetch --all --prune
git switch phase/04-fulfillment
```

A branch `main` contém somente fases aprovadas. Enquanto a Fase 4 não receber
aprovação final e merge, sua implementação estará em `phase/04-fulfillment`.
Confira sempre `project/state.json` e `project/phases/04-fulfillment.json`
antes de continuar.

## Ambiente local reproduzível

Requisitos: Git, Docker com Compose e, para execução direta, Python 3.12 e
`uv`. Não use SQLite.

```bash
cp .env.example .env
docker compose up -d db redis
uv sync --frozen --group dev
uv run python manage.py migrate
uv run python manage.py check
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
- `/fulfillment/` na branch da Fase 4.

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
- escopo e checkpoint: `project/phases/04-fulfillment.json`;
- contrato do domínio: `docs/domains/FULFILLMENT.md`;
- ciclo de vida: `docs/decisions/ADR-012-FULFILLMENT-LIFECYCLE.md`;
- concorrência: `docs/decisions/ADR-013-FULFILLMENT-CONSISTENCY.md`;
- fluxo completo: `docs/SYSTEM_FLOW.md`;
- caminho até produção: `docs/ROADMAP_TO_PRODUCTION.md`;
- processo de agentes: `AGENTS.md` e `docs/agents/`;
- evidência do candidato: `project/handoffs/phase-04.json`, quando gerada.

## Continuação segura

Não pule checkpoints. Depois da implementação: CI no SHA candidato, Review
independente, correções autorizadas, novo CI, QA/Segurança, handoff, aprovação
humana da fase e só então PR/merge autorizado. Payments começa apenas da main
que contenha Fulfillment aprovado.

Mercado Pago e Pagar.me permanecem planejados para a Fase 5; Appmax vem
depois. Nenhum provider, webhook, credencial ou máquina do Flowlog pode ser
reutilizado. Homologação e máquina exclusiva de produção pertencem à Fase 9;
go-live pertence à Fase 10.
