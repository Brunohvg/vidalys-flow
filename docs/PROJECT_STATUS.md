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
  `d36558636586b766a4d3b5b8f83abcb2505f78e0`.

`project/state.json` registra a Fase 3 como a última aprovação humana.

## Fase 3 — Orders

- branch: `phase/03-orders`;
- candidato material e evidência de CI: consultar
  `project/handoffs/phase-03.json`;
- planejamento: aprovado;
- implementação: completa;
- Review independente 1: alterações solicitadas e registradas em
  `project/reviews/phase-03-review-01.md`;
- Review independente 2: alterações solicitadas e registradas em
  `project/reviews/phase-03-review-02.md`;
- Review independente 3: alterações solicitadas e registradas em
  `project/reviews/phase-03-review-03.md`;
- Review independente 4: aprovado, registrado em
  `project/reviews/phase-03-review-04.md`;
- QA/Segurança: GO técnico, registrado em
  `project/qa/phase-03-qa-security.md`;
- aprovação humana da fase: recebida em 8 de agosto de 2026;
- PR da fase: merge concluído sem deploy.

O próximo checkpoint é o planejamento da Fase 4 — Fulfillment. A autorização
para iniciar essa fase não aprova previamente seu plano ou implementação.

## Independência do Flowlog

Foundation, Customers, Products e Orders não consultam mais o Flowlog. Não
existe acesso a runtime, banco, Redis, secrets, migrations, dados ou
infraestrutura do Flowlog.

## Escopo adiado

Fulfillment, Payments, Messaging, Integrations, Dashboard, infraestrutura,
homologação e cutover permanecem nas respectivas fases futuras. Estados
`completed`, `returned`, financeiros, de fulfillment e de providers não são
estados canônicos de Orders.
