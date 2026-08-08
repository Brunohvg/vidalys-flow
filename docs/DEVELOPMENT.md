# Desenvolvimento

## Ambiente

O caminho padrão exige somente Docker com Compose. Python 3.12, PostgreSQL 17,
Redis, Gunicorn e Celery ficam nos containers; nunca substitua os testes de
domínio por SQLite.

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
```

O serviço `migrate` aguarda PostgreSQL e Redis saudáveis. `web`,
`worker-default` e `beat` só iniciam depois que as migrations terminam com
sucesso. Configure as variáveis a partir de `.env.example`; não versionar
`.env`.

No WSL com Docker Engine local e sem `systemd`, inicie o daemon antes do
Compose e aguarde a seção `Server` aparecer:

```bash
sudo service docker start
docker info
```

Para acompanhar ou encerrar o ambiente:

```bash
docker compose logs -f web worker-default beat
docker compose down
```

## Checks

```bash
docker compose config
docker compose -f docker-compose.test.yml config
docker compose -f docker-compose.test.yml up --build \
  --abort-on-container-exit --exit-code-from test
```

O fluxo direto com `uv` continua opcional para quem já possui Python e os
serviços locais, mas não é requisito para desenvolvimento ou validação.

## Migrations

Migrations são geradas neste repositório e testadas desde banco vazio.
Não copiar, editar para compatibilidade ou marcar como aplicadas migrations
de outro sistema.

Os apps `customers`, `products`, `orders` e `fulfillment` possuem migrations iniciais
próprias. Para validar separadamente:

```bash
docker compose -f docker-compose.test.yml run --rm test \
  .venv/bin/pytest apps/fulfillment
```

Views são adaptadores. Escritas devem chamar services com `organization` e
ator explícitos; leituras devem usar selectors tenant-scoped. Não usar
`Model.objects.all()` em uma interface operacional.
