# Estado atual do projeto

Atualizado em 7 de agosto de 2026. Este documento é um índice operacional; em
caso de divergência prevalecem `project/state.json`, o manifesto da fase,
`project/constraints.json` e `AGENTS.md`.

## Produto aprovado

- Fase 0 — Audit: aprovada;
- Fase 1 — Foundation: aprovada em
  `6a97ac4b5af023f180b3d5282e3439c85e6721d2`;
- Fase 2 — Customers and Products: aprovada em
  `b28a019871274e9da1ca1cb65043c5e208b0e727`;
- baseline atual da Fase 3:
  `75c335676c6ad258e5ff2832bb64a2a5a7d97fcc`.

`project/state.json` continua registrando a Fase 2 como a última aprovação
humana. Nenhum resultado técnico da Fase 3 modifica esse fato.

## Candidato da Fase 3 — Orders

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
- checkpoint técnico corrente: consultar `project/handoffs/phase-03.json` e o
  relatório de Review mais recente;
- QA/Segurança: bloqueado até um Review sem bloqueadores;
- aprovação humana da fase: pendente.

QA só pode começar após um Review independente sem bloqueadores. Não iniciar
Fulfillment, PR, merge, release ou atualização de aprovação antes da conclusão
de Review, QA/Segurança e nova decisão humana.

## Independência do Flowlog

Foundation, Customers e Products não consultam mais o Flowlog. Orders possui
código greenfield independente, mas permanece na lista de referência histórica
até a aprovação formal da Fase 3. Não existe acesso a runtime, banco, Redis,
secrets, migrations, dados ou infraestrutura do Flowlog.

## Escopo adiado

Fulfillment, Payments, Messaging, Integrations, Dashboard, infraestrutura,
homologação e cutover permanecem nas respectivas fases futuras. Estados
`completed`, `returned`, financeiros, de fulfillment e de providers não são
estados canônicos de Orders.
