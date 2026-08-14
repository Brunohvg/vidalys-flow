# Vidalys Flow

Plataforma independente de operação de vendas e pós-venda.

> A Vidalys Flow é a sucessora funcional do Flowlog, mas é tecnicamente
> independente. Não consulta, importa, migra ou compartilha dados, runtime,
> autenticação ou infraestrutura com o Flowlog.

Este repositório contém a fundação greenfield e os domínios nativos e
aprovados de Customers, Products, Orders, Fulfillment e Payments. A Fase 06 —
Messaging possui um candidato em implementação, ainda sem Review, QA/Security
ou aprovação final; integrações gerais e dashboard permanecem posteriores.

Após selecionar uma organização permitida por Membership, as interfaces
estão disponíveis em:

- `/customers/`;
- `/products/`;
- `/orders/`;
- `/fulfillment/`;
- `/payments/` (aprovado, sem provider externo ativado);
- `/messaging/` (candidato da Fase 06, providers bloqueados).

Consulte [Customers](docs/domains/CUSTOMERS.md),
[Products](docs/domains/PRODUCTS.md), [Orders](docs/domains/ORDERS.md),
[Fulfillment](docs/domains/FULFILLMENT.md),
[Payments](docs/domains/PAYMENTS.md), o
[contrato candidato de Messaging](docs/domains/MESSAGING.md), o
[plano aprovado de Messaging](docs/domains/MESSAGING_VISION.md) e o
[relatório da referência histórica de
Messaging](docs/domains/MESSAGING_FLOWLOG_REFERENCE_AUDIT.md), além do
[estado atual do projeto](docs/PROJECT_STATUS.md) para regras, evidências e
decisões de escopo.

Para uma visão integrada, consulte o [fluxo funcional](docs/SYSTEM_FLOW.md), o
[caminho até produção](docs/ROADMAP_TO_PRODUCTION.md) e o
[plano aprovado de Payments](docs/domains/PAYMENTS_VISION.md). Para assumir o
trabalho em outro computador, siga [Clonar e continuar](docs/CLONE_AND_CONTINUE.md).

## Início rápido

Requisitos: Docker com Compose.

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
```

Esse único comando constrói a aplicação e inicia PostgreSQL 17, Redis, aplica
as migrations e só então libera web, worker Celery e scheduler Beat. Não é
necessário instalar Python, PostgreSQL, Redis ou `uv` no host. Se a porta 8000
já estiver ocupada, defina `VIDALYS_WEB_PORT` no `.env`.

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
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from test
```

O Compose de testes usa banco e Redis efêmeros e executa migrations, rollback
técnico, Ruff, Django checks, suíte PostgreSQL e cobertura dentro do container.

Consulte [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) para o fluxo completo.
