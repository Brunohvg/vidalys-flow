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
- Fase 4 — Fulfillment: material revisado em
  `70364bc7c8a381dc958b2c7e2976f6d28d015023`, evidências consolidadas em
  `7b2e92d939e9fd39b3baec1c12b900297a0d6548` e ratificação humana registrada
  após a auditoria de governança;
- merge de governança que registra a aprovação da Fase 3 em `main`:
  `a98ceab40f9c40d19dd9c24b666846fb05e63b2d`.

Orders e Fulfillment estão integrados à `main`. Nenhum deploy foi executado.

## Fase 4 — Fulfillment

- branch: `phase/04-fulfillment`;
- `actual_base_sha`: `a98ceab40f9c40d19dd9c24b666846fb05e63b2d`;
- dependência funcional aprovada: `d36558636586b766a4d3b5b8f83abcb2505f78e0`;
- plano: aprovado para implementação em 8 de agosto de 2026;
- implementação: concluída e remediada após o Review independente 01;
- candidato material: `70364bc7c8a381dc958b2c7e2976f6d28d015023`;
- evidência do candidato: 208 testes aprovados, nenhum skip e 86% de cobertura
  total no GitHub Actions run `31259856105`;
- ambiente local: PostgreSQL 17.10, Redis, web, worker Celery e Beat saudáveis
  em Docker, com migrations desde banco vazio e rollback técnico validados;
- Review independente 01: `CHANGES_REQUESTED`, com achados remediados;
- Review independente 02: `APPROVED` sem bloqueadores;
- QA/Segurança: `GO` técnico;
- merge da implementação: PR #3, commit `323861ef62db547a3947f63018a16b908cbc0f55`;
- aprovação final: ratificada explicitamente após a auditoria de governança;
- release e deploy: não autorizados.

O handoff e suas evidências estão em `project/handoffs/phase-04.json`. Os
pareceres estão em `project/reviews/phase-04-review-01.md` e
`project/reviews/phase-04-review-02.md`; o GO técnico está em
`project/qa/phase-04-qa-security.md`.

Fulfillment implementa lotes parciais de entrega ou retirada com estados
logísticos próprios, alocação quantitativa concorrente, idempotência e
privacidade. Ele não adiciona estoque, pagamento, provider nem estado novo a
Orders. A remediação padroniza locks em `Order -> Fulfillment`, amplia os
testes concorrentes e cross-organization, comprova sanitização e registra a
tarefa de cancelamento no worker Celery.

### Recuperação de governança

As PRs #3 e #5 foram mescladas antes de o fluxo de aprovação e a suíte de
governança estarem coerentes. A aprovação da Fase 4 foi posteriormente
ratificada pelo humano, sem reescrever o histórico. O relato completo e os CIs
vermelhos preservados estão em
`project/incidents/phase-04-governance-recovery.md`.

## Independência do Flowlog

Foundation, Customers, Products, Orders e Fulfillment não consultam mais o
Flowlog. Fulfillment foi elaborado a partir dos contratos aprovados da própria
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
