# Estado atual do projeto

Atualizado em 14 de agosto de 2026. Este documento é um índice operacional; em
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
  `3558ca30a5652be320feb3f28ab46a350ae9cad7`;
- Fase 6 — Messaging: aprovada em
  `e2140eb25cc10f1a79dad05a0507ba9141003ac9`.

A implementação de Payments entrou na `main` pela PR #8 e seu fechamento de
governança ocorreu pela PR #9. A implementação de Messaging entrou na `main`
pela PR #12, merge commit `e2140eb25cc10f1a79dad05a0507ba9141003ac9`, e
o fechamento de governança ocorreu pela PR #13, merge commit
`785084c85e96246e499e0edd1e3f96cd31f131a8`.

O GitHub Actions final da `main` após o fechamento da Fase 06 foi o run
`31791302546`, concluído com sucesso. Nenhum provider real, sandbox, callback
público, release ou deploy foi ativado.

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

## Fase 6 — Messaging

A Fase 6 está concluída e aprovada. O plano foi aprovado, a implementação foi
concluída, o Review 03 emitiu `APPROVED`, o QA/Security emitiu `GO`, o achado
documental P06-R09 foi corrigido e a aprovação humana final autorizou o
fechamento, PR e merge após CI verde.

Messaging implementa mensagens exclusivamente transacionais, com núcleo
canônico independente de provider, templates fechados e versionados, regras
automáticas inicialmente desabilitadas por Organization, permissão por
finalidade com comportamento fail-closed e revalidação de links de pagamento
imediatamente antes do envio.

Foram implementados contratos offline e provider-neutral para Evolution API
v2.3.7 linked-device, WhatsApp Cloud API direta e Amazon SES. Os efeitos
externos permanecem desabilitados. Credenciais reais, pairing real, sandbox,
callbacks públicos, consultas externas de status, ativação de produção e
deploy continuam fora da autorização concedida para a Fase 06.

A implementação final preserva autorização atômica antes de I/O, imutabilidade
de templates e snapshots, idempotência, versionamento de regras, tratamento de
aceitação ambígua sem retry cego, contratos exatos de versão de eventos e um
catálogo server-side fechado de templates transacionais. A matriz cobre as seis
fontes automáticas aprovadas e os casos negativos de versão, estado e conteúdo
promocional.

O contrato oficial está em `project/phases/06-messaging.json`, a visão em
`docs/domains/MESSAGING_VISION.md`, o contrato entregue em
`docs/domains/MESSAGING.md`, os Reviews em `project/reviews/`, o QA/Security em
`project/qa/phase-06-qa-security.md` e o handoff final em
`project/handoffs/phase-06.json`.

## Próximo checkpoint — Fase 7 Integrations

A Fase 7 — Integrations é a próxima fase prevista no roadmap, mas ainda não foi
iniciada. `project/state.json` mantém `active_candidate: null`. Planejamento,
branch de candidato, implementação ou qualquer alteração de escopo da Fase 7
exigem nova autorização humana explícita.

Também continuam sem autorização provider real, deploy, homologação, cutover ou
qualquer efeito externo adiado pelas fases anteriores.

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
