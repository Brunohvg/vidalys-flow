# Review independente 02 — Fase 06 Messaging

- resultado: `CHANGES_REQUESTED`;
- candidato material revisado: `a98e69b7f0d530956a095bc4757a9b4848c1083b`;
- baseline: `3e4fcfb064fbee350d3df131b2946974c8557098`;
- dependency head: `3558ca30a5652be320feb3f28ab46a350ae9cad7`;
- carrier observado: `6bb3f533327fc47c6ba83536b3644b8b5129c28d`;
- CI material: run `31758178500`, sucesso no SHA exato;
- CI do carrier: run `31758401999`, sucesso no SHA exato;
- verificacao local: 396 testes aprovados, 5 skips de governanca dependentes
  de `.git`, 124 testes diretos de Messaging e cobertura registrada de
  85,298304%;
- QA/Seguranca: permanece bloqueado ate remediacao e novo Review independente.

## Revalidacao do Review 01

| Achado | Resultado | Evidencia resumida |
| --- | --- | --- |
| P06-R01 | resolvido | `prepare_send_request` trava Message, attempt e dependencias, revalida, move para `sending` e monta o request numa unica transacao; fonte, checkout, supressao, contato, merge e canal possuem regressoes PostgreSQL |
| P06-R02 | resolvido | manager imutavel, verificacao no `save` e triggers PostgreSQL protegem template usado e snapshots/relacionamentos de Message; testes exercitam ORM e SQL direto |
| P06-R03 | resolvido | hash inclui `is_enabled` e `expected_version`; regras usam lock, versao crescente e conflito otimista; template valida stale version; corrida aceita uma unica atualizacao |
| P06-R04 | resolvido | somente `MessagingDomainError` cria rejeicao definitiva; falha transitoria/inesperada nao cria receipt e o evento volta a ser selecionado |
| P06-R05 | resolvido quanto aos blockers originais | as reproducoes de R01 a R04 foram adicionadas e passam; a matriz normativa completa ainda possui as lacunas do novo P06-R08 |

## Novos achados bloqueadores

### P06-R06 — Alta — `event_version` da regra existe, mas nao participa do consumo

**Evidencia:** `MessageAutomationRule.event_version` existe em
`apps/messaging/models.py:270`, porem nenhuma referencia executavel fora do
model/migration foi encontrada. `upsert_automation_rule` nao recebe nem
persiste a versao de contrato. `consume_source_event` filtra apenas
Organization, `event_type` e `is_enabled` em
`apps/messaging/services.py:538-542`. O campo `payload["version"]` validado no
mesmo service e a versao do agregado de origem, usada depois como
`Message.source_version`; nao e uma versao do schema do evento.

**Reproducao PostgreSQL executada:** uma regra habilitada
`order.confirmed` com `event_version=999` consumiu normalmente um evento
emitido pelo contrato atual e criou a Message (`EVENT_PROCESSED 1`,
`AUTO_CREATED True`).

**Impacto:** uma mudanca incompativel no envelope/payload que preserve o mesmo
`event_type` nao pode ser rejeitada pela versao aprovada. O campo persistido
gera falsa evidencia de compatibilidade e viola a exigencia de consumir
somente a versao exata allowlisted.

**Recomendacao:** separar explicitamente `event_contract_version` da versao
do agregado no envelope sanitizado, inclui-la no comando/hash e snapshot da
regra e exigir igualdade no consumidor antes de resolver a fonte. Rejeitar
versao ausente/desconhecida e testar cada versao permitida e proibida.

### P06-R07 — Alta — template promocional/arbitrario continua estruturalmente elegivel

**Evidencia:** `create_template` aceita qualquer `semantic_key`, `name`,
`body_text` e `body_html` fornecidos por manager em
`apps/messaging/services.py:1652-1719`. `MessageTemplate` nao possui `purpose`
nem estado/evidencia de aprovacao transacional. `_create_message` valida
canal, placeholders e parametros, mas nao associa semantic key ou conteudo a
uma finalidade aprovada. O formulario expõe os corpos livremente.

**Reproducao PostgreSQL executada:** foi criado pela API de dominio um template
ativo `semantic_key=promotion`, corpo estatico
`PROMOCAO: compre novamente com desconto` e schema vazio. Um comando manual
de `order_confirmation` criou a Message com sucesso
(`PROMOTIONAL_MANUAL_CREATED True`); a mesma definicao tambem foi aceita por
uma regra automatica.

**Impacto:** marketing e texto arbitrario, ambos proibidos na Fase 06, podem
ser enviados sob a finalidade transacional de confirmacao. O vinculo a um
Order nao transforma conteudo promocional em template aprovado e operadores
podem usar depois a configuracao criada por manager.

**Recomendacao:** tornar estrutural a aprovacao: vincular cada versao de
template a uma finalidade/caso semantico allowlisted e impedir que criacao
livre a torne imediatamente ativa. Usar catalogo fechado server-side ou um
checkpoint de aprovacao com politicas executaveis que nao permita marketing;
manual e automacao devem validar esse vinculo antes da Message e do dispatch.

### P06-R08 — Alta — matriz normativa ainda nao cobre os contratos acima nem todas as fontes automaticas

**Evidencia:** os testes de consumo automatico em
`apps/messaging/tests/test_tasks.py` exercitam somente `order.confirmed`.
Nao ha teste automatico de `fulfillment.ready`,
`fulfillment.dispatched`, `fulfillment.completed`,
`payment.checkout_activated` ou `payment.status_changed`, embora o manifesto
exija criacao automatica de cada fonte allowlisted. Nao existe teste de
`event_version` divergente, porque o campo nao e consumido, nem teste que
rejeite template promocional/arbitrario. A busca direta por `event_version`
na suite nao retorna ocorrencias.

**Impacto:** CI e cobertura permanecem verdes enquanto P06-R06 e P06-R07
violam contratos expressos. A evidencia de 124 testes diretos nao satisfaz o
gate comportamental literal para fontes, schema do evento e escopo
transacional.

**Recomendacao:** adicionar uma matriz parametrizada com todos os eventos,
estados elegiveis/ineligiveis, versoes de contrato, cross-Organization e
replays; adicionar testes negativos de semantic key/purpose/conteudo fora do
catalogo aprovado.

## Verificacoes independentes aprovadas

- merge-base da baseline e candidato:
  `3e4fcfb064fbee350d3df131b2946974c8557098`;
- dependency head e ancestral da baseline e do candidato;
- o carrier altera exclusivamente `project/handoffs/phase-06.json`;
- runs `31758178500` e `31758401999` confirmados `success` nos SHAs exatos;
- migrations 0001/0002 aplicaram desde PostgreSQL vazio e rollback/reapply de
  Messaging passou;
- suite Compose completa passou com 401 itens coletados, sendo 396 passed e
  5 skipped; suite direta de Messaging: 124 passed;
- `validate-all`, secret scan, independence scan, Ruff, Django check,
  migration consistency, `git diff --check` e topologia Celery passaram;
- autorizacao, Membership, Organization, callbacks fail-closed, PII
  sanitizada, provider-neutralidade e bloqueio de rede nao apresentaram nova
  regressao bloqueante no delta;
- nenhum provider, sandbox, Flowlog, secret, PR, merge ou deploy foi acessado.

## Riscos residuais corretamente adiados

- Evolution linked-device permanece nao oficial, sem pairing ou rede real;
- autenticidade completa Meta e SES/SNS e o secret resolver Evolution
  permanecem bloqueados para callback publico;
- fixtures offline nao equivalem a homologacao de provider;
- infraestrutura, credenciais, destinatarios reais, sandbox e producao exigem
  autorizacoes posteriores separadas.

## Conclusao

O parecer e `CHANGES_REQUESTED`. P06-R01 a P06-R05 foram resolvidos, mas
P06-R06 a P06-R08 precisam de remediacao material, testes e novo CI antes de
outro Review independente. QA/Security permanece bloqueado.
