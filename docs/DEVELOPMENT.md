# Desenvolvimento

## Ambiente

Use Python 3.12, PostgreSQL 17 e Redis. Nunca substitua os testes de domínio
por SQLite.

```bash
uv sync --frozen --group dev
docker compose up -d db redis
uv run python manage.py migrate
```

Configure as variáveis a partir de `.env.example`; não versionar `.env`.

## Checks

```bash
uv run ruff check .
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run coverage run -m pytest
uv run coverage report
uv run python scripts/check_secrets.py
uv run python scripts/check_independence.py
docker compose config
docker compose -f docker-compose.test.yml config
```

## Migrations

Migrations são geradas neste repositório e testadas desde banco vazio.
Não copiar, editar para compatibilidade ou marcar como aplicadas migrations
de outro sistema.

Os apps `customers`, `products` e `orders` possuem migrations iniciais
próprias. Para validar separadamente:

```bash
uv run pytest apps/customers
uv run pytest apps/products
uv run pytest apps/orders
```

Views são adaptadores. Escritas devem chamar services com `organization` e
ator explícitos; leituras devem usar selectors tenant-scoped. Não usar
`Model.objects.all()` em uma interface operacional.
