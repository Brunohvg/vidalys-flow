# Vidalys Flow

Plataforma independente de operação de vendas e pós-venda.

> A Vidalys Flow é a sucessora funcional do Flowlog, mas é tecnicamente
> independente. Não consulta, importa, migra ou compartilha dados, runtime,
> autenticação ou infraestrutura com o Flowlog.

Este repositório contém a fundação greenfield e os domínios nativos de
clientes, catálogo operacional de produtos e o candidato da Fase 3 — Orders.
Orders ainda depende de Review independente, QA/Segurança e aprovação humana;
fulfillment, pagamentos, mensagens, integrações e dashboard permanecem fora do
escopo atual.

Após selecionar uma organização permitida por Membership, as interfaces
estão disponíveis em:

- `/customers/`;
- `/products/`;
- `/orders/` na branch candidata `phase/03-orders`.

Consulte [Customers](docs/domains/CUSTOMERS.md) e
[Products](docs/domains/PRODUCTS.md), [Orders](docs/domains/ORDERS.md) e o
[estado atual do projeto](docs/PROJECT_STATUS.md) para regras, evidências e
decisões de escopo.

Para uma visão integrada, consulte o [fluxo funcional](docs/SYSTEM_FLOW.md), o
[caminho até produção](docs/ROADMAP_TO_PRODUCTION.md) e a
[visão futura de Payments](docs/domains/PAYMENTS_VISION.md).

## Início rápido

Requisitos: Docker com Compose.

```bash
cp .env.example .env
docker compose up -d db redis
docker compose --profile release run --rm migrate
docker compose up -d web worker-default beat
```

Se a porta 8000 já estiver ocupada, defina `VIDALYS_WEB_PORT` no `.env`.

Crie a primeira organização:

```bash
docker compose exec web .venv/bin/python manage.py bootstrap_organization \
  --organization-name "Minha empresa" \
  --slug "minha-empresa" \
  --owner-email "owner@example.com" \
  --owner-name "Nome do Owner" \
  --unit-name "Matriz"
docker compose exec web .venv/bin/python manage.py changepassword owner@example.com
```

O bootstrap nunca recebe a senha como argumento e não a imprime.

## Validação

```bash
uv sync --frozen --group dev
uv run python scripts/check_secrets.py
uv run python scripts/check_independence.py
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from test
```

Consulte [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) para o fluxo completo.
