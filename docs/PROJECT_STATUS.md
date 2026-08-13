# Estado atual do projeto

Atualizado em 12 de agosto de 2026. Este documento é um índice operacional; em
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
- Fase 4 — Fulfillment: aprovada em
  `888685886d7a17c6eeb008674be86656e4f6fa40`;
- Fase 5 — Payments: aprovada em
  `3558ca30a5652be320feb3f28ab46a350ae9cad7`.

A implementação de Payments entrou na `main` pela PR #8, cujo merge commit é
`3558ca30a5652be320feb3f28ab46a350ae9cad7`. A aprovação humana e o estado
oficial foram fechados pela PR #9, merge commit
`3e4fcfb064fbee350d3df131b2946974c8557098`. O GitHub Actions final da `main`,
run `31651983767`, passou nesse SHA.

Nenhum provider, sandbox, callback público, release ou deploy foi ativado.

## Fase 5 — Payments

Payments implementa intents financeiros canônicos para o valor integral em
BRL de um Order confirmado, uma tentativa ativa por vez, links de checkout
hospedado, adapters desabilitados de Mercado Pago e Pagar.me, callbacks
verificados, reconciliação e cancelamento correlacionado. O provider nunca
dita o estado canônico e Payments não muda Order nem Fulfillment.

Após ciclos de Review e remediação, o Review 05 emitiu `APPROVED`. O QA/Security
final emitiu `GO`: 277 testes PostgreSQL sem skip, 70 testes diretos de
Payments, cobertura exata de 85,24744994333207%, migrations desde banco vazio,
rollback/reaplicação e topologia Celery real com workers exclusivos para
`default` e `integrations`. Relatórios e handoff permanecem em
`project/reviews/`, `project/qa/` e `project/handoffs/phase-05.json`.

Mercado Pago Checkout Pro é o primeiro rollout planejado; Pagar.me v5 Payment
Links é o segundo e Appmax permanece posterior. Isso não significa que nenhum
deles esteja habilitado: credenciais, sandbox e produção exigem checkpoints
separados.

## Checkpoint atual — Fase 6 Messaging

- branch: `phase/06-messaging`;
- `actual_base_sha`: `3e4fcfb064fbee350d3df131b2946974c8557098`;
- dependência funcional: Payments aprovada em
  `3558ca30a5652be320feb3f28ab46a350ae9cad7`;
- plano: proposto, pendente de aprovação humana;
- implementação, Review e QA/Security: bloqueados;
- efeitos externos, sandbox, PR, merge e deploy: não autorizados.

O plano propõe mensagens exclusivamente transacionais, com núcleo canônico
independente de provider, Evolution API v2.3.7 linked-device primeiro,
WhatsApp Cloud API direta como alternativa oficial e Amazon SES depois.
Templates são fechados e versionados, regras automáticas começam desabilitadas
por Organization, permissão por finalidade falha fechado e links de pagamento
são revalidados imediatamente antes do envio. Marketing, inbound, chatbot, IA,
SMS e anexos ficam adiados.

O contrato completo e as decisões humanas necessárias estão em
`project/phases/06-messaging.json` e
`docs/domains/MESSAGING_VISION.md`. Não existe código de Messaging nesta
branch enquanto o plano não for aprovado.

## Independência do Flowlog

Após autorização humana explícita, o planejamento de Messaging consultou
somente os caminhos registrados de Messaging no SHA congelado do Flowlog, em
modo leitura, para entender o adapter Evolution e as falhas do legado. Nada foi
copiado ou conectado. A Vidalys Flow não consulta em runtime, importa, migra
ou compartilha código, banco, Redis, arquivos, contatos, templates, mensagens,
usuários, IDs, autenticação, secrets, workers, webhooks, servidor ou
infraestrutura com o sistema antigo.

## Infraestrutura

A arquitetura e o Compose usam PostgreSQL, Redis, workers e aplicação próprios
da Vidalys Flow. O repositório não comprova máquina de produção provisionada;
homologação e infraestrutura exclusiva pertencem à Fase 9. O go-live pertence
à Fase 10 e continua sem autorização.
