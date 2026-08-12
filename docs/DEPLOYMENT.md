# Deployment

Esta fase não configura um ambiente Coolify real.

Também não existe, neste repositório, evidência de uma máquina de produção já
provisionada. A arquitetura exige ambiente computacional, PostgreSQL, Redis,
secrets, DNS e observabilidade exclusivos da Vidalys Flow. Nada poderá ser
compartilhado ou reutilizado do Flowlog antigo.

A imagem usa Python 3.12, dependências travadas, usuário não-root, static
coletado no build e healthcheck de liveness. O Compose local demonstra:

- `web`;
- `worker-default`;
- `worker-integrations`;
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
4. iniciar web, os workers `default` e `integrations` e o Beat;
5. validar `/health/live/` e `/health/ready/`;
6. executar o bootstrap e definir a senha por canal seguro.

Provisionamento, homologação, backup/restore, observabilidade, segurança de
rede e autorização de deploy pertencem à Fase 09. Consulte
`docs/ROADMAP_TO_PRODUCTION.md`.
