# Estado atual do projeto

Atualizado em 8 de agosto de 2026. Este documento é um índice operacional; em
caso de divergência prevalecem `project/state.json`, o manifesto da fase,
`project/constraints.json` e `AGENTS.md`.

## Produto aprovado

- Fase 0 — Audit: aprovada;
- Fase 1 — Foundation: aprovada em
  `6a97ac4b5af023f180b3d5282e3439c85e6721d2`;
- Fase 2 — Customers and Products: aprovada em
  `b28a019871274e9da1ca1cb65043c5e208b0e727`;
- Fase 3 — Orders: aprovada em
  `d36558636586b766a4d3b5b8f83abcb2505f78e0`;
- merge de governança que registra a aprovação da Fase 3 em `main`:
  `a98ceab40f9c40d19dd9c24b666846fb05e63b2d`.

Orders concluiu implementação, Review independente, QA/Segurança, aprovação
humana e merge. Nenhum deploy foi executado.

## Fase 4 — Fulfillment

- branch: `phase/04-fulfillment`;
- `actual_base_sha`: `a98ceab40f9c40d19dd9c24b666846fb05e63b2d`;
- dependência funcional aprovada: `d36558636586b766a4d3b5b8f83abcb2505f78e0`;
- plano: aprovado para implementação em 8 de agosto de 2026;
- implementação: candidata e remediada após o Review independente 01;
- evidência local: 208 testes aprovados, nenhum skip e 86% de cobertura total;
- ambiente local: PostgreSQL 17.10, Redis, web, worker Celery e Beat saudáveis
  em Docker, com migrations desde banco vazio e rollback técnico validados;
- Review independente 01: `CHANGES_REQUESTED`, com achados remediados no novo
  candidato e novo Review ainda pendente;
- CI do candidato remediado: pendente;
- QA/Segurança: bloqueado até CI e novo Review sem bloqueadores;
- PR, merge, release e deploy: não autorizados neste checkpoint.

O handoff candidato, o SHA material vigente e suas evidências estão em
`project/handoffs/phase-04.json`. O primeiro parecer independente está em
`project/reviews/phase-04-review-01.md`.

O candidato implementa lotes parciais de entrega ou retirada com estados
logísticos próprios, alocação quantitativa concorrente, idempotência e
privacidade. Ele não adiciona estoque, pagamento, provider nem estado novo a
Orders. A remediação padroniza locks em `Order -> Fulfillment`, amplia os
testes concorrentes e cross-organization, comprova sanitização e registra a
tarefa de cancelamento no worker Celery.

## Independência do Flowlog

Foundation, Customers, Products e Orders não consultam mais o Flowlog. O plano
de Fulfillment foi elaborado a partir dos contratos aprovados da própria
Vidalys Flow, sem consultar código legado. Não existe acesso ou vínculo com
runtime, banco, Redis, secrets, migrations, dados, IDs, providers, servidor ou
infraestrutura do Flowlog.

## Pagamentos e infraestrutura

Payments permanece na Fase 5. Mercado Pago e Pagar.me são os primeiros
conectores planejados para links de pagamento; Appmax permanece posterior e
todos exigirão contrato, sandbox, webhook e aprovação próprios.

A arquitetura exige máquina, PostgreSQL, Redis, secrets e observabilidade
exclusivos da Vidalys Flow. O repositório não comprova que a máquina de
produção já foi provisionada; isso será verificado na Fase 9. Deploy continua
pendente.
