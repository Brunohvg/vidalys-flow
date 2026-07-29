# Deployment

Esta fase não configura um ambiente Coolify real.

A imagem usa Python 3.12, dependências travadas, usuário não-root, static
coletado no build e healthcheck de liveness. O Compose local demonstra:

- `web`;
- `worker-default`;
- `beat`;
- PostgreSQL 17;
- Redis;
- release explícito de migrations.

Produção exige `config.settings.production`, `SECRET_KEY`, `DATABASE_URL`,
hosts/origens e recursos PostgreSQL/Redis exclusivos. A ausência de
`VIDALYS_DEMO_MODE` mantém efeitos externos bloqueados.

Procedimento conceitual:

1. criar banco e Redis vazios e exclusivos;
2. construir a imagem pelo commit aprovado;
3. executar migrations pelo serviço de release;
4. iniciar web, worker e Beat;
5. validar `/health/live/` e `/health/ready/`;
6. executar o bootstrap e definir a senha por canal seguro.
