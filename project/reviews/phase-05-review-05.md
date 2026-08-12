# Review independente 05 — Fase 05 Payments

- decisão: `APPROVED`;
- checkpoint: Review independente focado exclusivamente na remediação do
  NO-GO de QA/Security, sem correção de código e sem nova execução de QA;
- branch: `phase/05-payments`;
- candidato material revisado:
  `09fe3615008fe1621e46ecee74d6a2b58667377b`;
- carrier observado: `570dd8c55c69465ca69dc90fbebfa2ed3c079e81`;
- baseline (`actual_base_sha`):
  `4fd3a9259e9e2f31acdab44f13499eade79ab59e`;
- dependência aprovada:
  `888685886d7a17c6eeb008674be86656e4f6fa40`;
- CI material: run `31585187061`, sucesso no SHA exato;
- CI do carrier: run `31585362155`, sucesso no SHA exato;
- blockers críticos, altos ou médios: nenhum.

## Fronteira focada e prevenção de novo ciclo

Este Review não repetiu a investigação histórica dos quatro Reviews anteriores.
Foi revisado em profundidade o delta material
`f66f201694f5a39fc4ff0c8122467a239ed6af97..09fe3615008fe1621e46ecee74d6a2b58667377b`,
limitado à descoberta das tasks de Payments, topologia de filas e workers,
gate operacional, testes e documentação do NO-GO. O intervalo
`09fe361..570dd8c` altera somente o manifesto e o handoff.

A dependência aprovada é ancestral da baseline, a baseline é ancestral do
candidato e não há merge commit no intervalo. `origin/main` permaneceu em
`4fd3a9259e9e2f31acdab44f13499eade79ab59e`.

## Revalidação do NO-GO anterior

| Achado | Resultado | Evidência resumida |
| --- | --- | --- |
| P05-Q01 | resolvido | `apps.payments` participa do autodiscovery; runtime reconstruído registrou `consume_order_cancellations`, `dispatch_checkout_requests` e `dispatch_checkout_cancellations` nos dois workers |
| P05-Q02 | resolvido | Compose declara workers distintos para `default` e `integrations`; ambos ficaram saudáveis e cada um consumiu exclusivamente sua fila |
| P05-Q03 | resolvido no conteúdo operacional, com ressalva baixa | arquitetura, desenvolvimento, deploy, status, roadmap e contratos descrevem o NO-GO e a remediação; uma frase inicial do guia de clone ainda chama o candidato de “segunda remediação” |

### P05-R22 — baixo, não bloqueante — rótulo histórico no guia de clone

`docs/CLONE_AND_CONTINUE.md` ainda descreve a branch como contendo a “segunda
remediação candidata”, embora a seção de continuidade e os demais documentos
registrem corretamente a remediação operacional posterior ao Review 04 e ao
NO-GO. O erro não muda SHA, comando de clone, checkpoint, escopo ou operação e
não justifica outro ciclo de implementação/Review. Deve ser alinhado na
atualização documental do fechamento da fase.

## Celery e robustez do gate

O runtime Compose foi reconstruído a partir do candidato. `migrate` concluiu,
Beat e os dois workers passaram seus healthchecks. A inspeção real confirmou:

- `worker-default`: somente fila `default`, exchange direto `vidalys`, routing
  key `default`;
- `worker-integrations`: somente fila `integrations`, exchange direto
  `vidalys`, routing key `integrations`;
- as seis tasks agendadas/roteadas estão registradas, incluindo as três de
  Payments;
- outbox e consumidores internos são efetivamente roteados a `default`;
- dispatch e cancelamento de checkout são efetivamente roteados a
  `integrations`.

Como o exchange é `direct` e as routing keys são distintas, uma mensagem
publicada para `default` não possui binding com `integrations`, e vice-versa.
O script `check_celery_runtime.py` cruza agenda e rotas com o registro real,
filas declaradas, bindings únicos e filas consumidas no Compose. Cenários
negativos independentes comprovaram falha fechada para task não registrada,
fila sem consumer e binding ambíguo. O gate é executado no CI após a validação
dos dois arquivos Compose.

Os containers efêmeros de Beat, migration e workers foram removidos ao final;
PostgreSQL e Redis locais preexistentes permaneceram intactos.

## Gates independentes

- `validate-all`: passou;
- baseline/governança com `origin/main`: passou;
- scanners de secrets e independência: passaram;
- Ruff, Django check, migration consistency e `git diff --check`: passaram;
- gate de topologia Celery: passou;
- suíte PostgreSQL: 277 aprovados, nenhum skip;
- cobertura exata: 85,24744994333207%, acima do mínimo de 85%;
- Payments direto: 70 aprovados;
- runtime Compose: Beat, `worker-default` e `worker-integrations` saudáveis;
- CI material `31585187061`: `success` em `09fe361...`;
- CI do carrier `31585362155`: `success` em `570dd8c...`.

## Núcleo e limites preservados

O delta não altera models, migrations, services, callbacks, adapters ou
interfaces de Payments. Permanecem preservados o valor integral do Order em
BRL, snapshots imutáveis, locks, idempotência, isolamento por Organization,
evidência sanitizada e efeitos externos bloqueados. O callback Pagar.me segue
bloqueado em aplicação e PostgreSQL; Mercado Pago não recebeu credencial nem
chamada; Appmax e Flowlog permanecem ausentes. Não houve sandbox, provider,
webhook público, PR, merge, release ou deploy.

## Parecer

`APPROVED`. P05-Q01 e P05-Q02 estão resolvidos no código, no gate e no runtime
real. P05-Q03 está materialmente resolvido; P05-R22 é uma imprecisão temporal
baixa e não bloqueante a ser corrigida no fechamento documental, sem abrir
novo ciclo técnico. Este parecer libera somente uma nova execução independente
de QA/Security mediante autorização humana. Não aprova produto, alteração de
`project/state.json`, sandbox, provider, PR, merge, release, deploy ou fase
posterior.
