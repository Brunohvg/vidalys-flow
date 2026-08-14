# Review independente 01 — Fase 06 Messaging

- resultado: `CHANGES_REQUESTED`;
- candidato material revisado: `e09dfabd77aba4e088cfae8d26bd6a91a11440ee`;
- baseline: `3e4fcfb064fbee350d3df131b2946974c8557098`;
- dependency head: `3558ca30a5652be320feb3f28ab46a350ae9cad7`;
- carrier observado: `eb9bded670dcbff8709dec21e7903c96e461ce9a`;
- CI material: run `31756127273`, sucesso no SHA exato;
- CI do carrier: run `31756306732`, sucesso no SHA exato;
- verificacao local: 386 testes aprovados, 5 skips de testes que exigem `.git`
  ausente na imagem, e cobertura registrada no candidato de 85,238841%;
- QA/Seguranca: bloqueado ate remediacao, novo CI e novo Review independente.

## Achados bloqueadores

### P06-R01 — Alta — revalidacao perde os locks antes da chamada externa

**Evidencia:** `dispatch_message` chama `build_send_request` em
`apps/messaging/services.py:944-958`. Essa funcao abre sua propria transacao,
trava Message e fontes e revalida Customer, contato, permissao, template,
canal, conexao e checkout em `apps/messaging/services.py:740-810`. A transacao
termina ao devolver `SendRequest`. Somente depois, em outra transacao,
`mark_sending` altera o estado, e a chamada `adapter.send_text` ocorre em
`apps/messaging/services.py:959-969`. `mark_sending` trava apenas Message e
attempt; nao relê fonte, permissao, contato, canal ou conexao.

**Impacto:** entre a montagem do request e o I/O, outro comando pode suprimir
o contato, mesclar o Customer, alterar/cancelar a fonte, expirar/substituir o
checkout ou desabilitar canal/conexao. Mesmo assim, o request ja montado —
inclusive com URL de checkout — pode ser enviado. Isso viola a revalidacao
"imediatamente antes do dispatch" e torna insuficientes os locks declarados
no manifesto e no handoff.

**Reproducao:** introduzir uma barreira depois de `build_send_request`, alterar
uma `MessagingPreference` para `suppressed` (ou desabilitar o canal) numa
segunda conexao PostgreSQL e liberar a barreira. O adapter fake ainda recebe
uma chamada. A suite possui disputa entre dois dispatchers imediatos, mas nao
essa corrida com mudanca de elegibilidade.

**Recomendacao:** estabelecer uma fronteira de dispatch que preserve uma
autorizacao/lease verificavel ate o I/O ou revalidar novamente todas as
dependencias depois de marcar `sending` e imediatamente antes da chamada,
com protocolo explicito para mudancas concorrentes. Cobrir supressao, merge,
fonte, checkout e canal concorrentes em PostgreSQL.

### P06-R02 — Alta — templates usados e snapshots de Message podem ser reescritos

**Evidencia:** `MessageTemplate.save` em
`apps/messaging/models.py:202-205` bloqueia apenas `save()` de uma instancia
usada. O model usa o manager padrao, portanto
`MessageTemplate.objects.filter(...).update(body_text=..., parameter_schema=...)`
contorna a protecao. Nao ha trigger PostgreSQL nem `QuerySet` imutavel para o
template. `Message` usa `ImmutableQuerySet` somente para update/bulk update e
delete; seu `save()` nao protege `destination_snapshot`, fonte, template,
parametros, permissao ou Organization. O body e relido do template apenas no
dispatch em `apps/messaging/services.py:790-810`.

**Impacto:** uma versao de template ja vinculada pode produzir conteudo
diferente do aprovado e uma Message pendente pode ter seus snapshots
reescritos sem history, audit, outbox ou incremento controlado de versao. A
garantia de versao imutavel e de evidencia deterministica do handoff nao e
verdadeira em todas as superficies ORM.

**Reproducao:** criar uma Message, executar
`MessageTemplate.objects.filter(pk=message.template_id).update(body_text='...')`
e chamar `build_send_request`; o novo corpo e renderizado. De forma analoga,
alterar `message.destination_snapshot` e chamar `message.save()` persiste o
novo destino.

**Recomendacao:** proteger os campos imutaveis no model/manager e, em
proporcao ao risco, no PostgreSQL; permitir somente as transicoes canonicas
necessarias. Adicionar testes de `save`, `update` e `bulk_update` depois do uso.

### P06-R03 — Alta — comandos de configuracao violam idempotencia, versao e concorrencia otimista

**Evidencia:** o hash de `upsert_automation_rule` em
`apps/messaging/services.py:1761-1773` omite `is_enabled`. Assim, a mesma chave
aceita comandos semanticamente diferentes. O `update_or_create` fixa
`version: 1` nos defaults e depois incrementa o objeto retornado; atualizacoes
sucessivas produziram `1 -> 2 -> 2`, em vez de versao crescente. O comando
tambem nao recebe `expected_version`. `deactivate_template`, embora receba
`expected_version`, nunca chama `_ensure_version` em
`apps/messaging/services.py:1648-1670`.

**Reproducao PostgreSQL executada:** tres upserts da mesma regra com chaves
novas produziram `VERSIONS 1 2 2`. Reutilizar uma chave com `is_enabled=True`
e depois `False` nao gerou `IdempotencyConflict`; o segundo comando retornou o
resultado anterior. `deactivate_template(expected_version=999)` desativou um
template de versao 1.

**Impacto:** replay divergente nao e detectado, a versao deixa de representar
a ordem real das mudancas e edicoes concorrentes podem sobrescrever decisao
de habilitar/desabilitar automacao. Um stale form consegue desativar template.
Isso contradiz `MessageCommandReceipt`, `expected_version` e a exigencia de
evitar sobrescritas concorrentes.

**Recomendacao:** incluir todo campo de comando no hash; travar a regra e
incrementar sua versao atual sem reset; exigir `expected_version` em updates;
aplicar `_ensure_version` a template e demais comandos; testar replay
divergente e edicoes simultaneas em PostgreSQL.

### P06-R04 — Alta — falha transitoria no consumidor e registrada como rejeicao definitiva

**Evidencia:** `consume_source_events` captura `Exception` sem classificacao
em `apps/messaging/tasks.py:37-45` e grava imediatamente um receipt concluido
com operacao `consume_source_event_rejected`. A consulta seguinte exclui esse
event ID para sempre. Dentro de `consume_source_event`, falhas de cada regra
tambem sao silenciosamente descartadas em `apps/messaging/services.py:540-555`.

**Impacto:** timeout PostgreSQL, indisponibilidade momentanea, erro de lock ou
defeito inesperado pode transformar um evento aprovado de Orders,
Fulfillment ou Payments em perda permanente sem retry, dead-letter ou
evidencia operacional do motivo. O outbox continua intacto, mas Messaging o
marca como consumido e nunca volta a observa-lo.

**Reproducao:** substituir temporariamente `consume_source_event` por uma
funcao que lance `OperationalError`, executar `consume_source_events` e
restaurar a funcao. Existe um receipt `consume_source_event_rejected`
concluido e a segunda execucao nao seleciona o evento.

**Recomendacao:** rejeitar definitivamente apenas erros de contrato
classificados; erros transitorios devem preservar elegibilidade, aplicar
backoff e tentativas limitadas, e falhas inesperadas devem produzir evidencia
sanitizada/dead-letter. Cobrir lote misto e recuperacao apos falha transitoria.

### P06-R05 — Alta — matriz critica de testes nao detecta os blockers

**Evidencia:** a suite direta de Messaging cobre fluxo nominal, callbacks
sinteticos e duas corridas imediatas. Nao cobre a janela entre revalidacao e
I/O, mutacao ORM de template usado/Message snapshot, concorrencia de regras,
replay divergente por `is_enabled`, stale version de template, nem retry de
evento depois de falha transitoria. Os testes existentes inclusive confirmam
`version == 2` em uma unica atualizacao, mas nao executam a terceira que revela
a regressao.

**Impacto:** 386 testes, CI verde e cobertura superior a 85% nao exercitam as
invariantes que falham acima. Isso nao atende a expectativa de testes diretos
para permission/source freshness, snapshots, idempotencia e concorrencia.

**Recomendacao:** adicionar os cenarios de reproducao acima, mantendo
PostgreSQL 17 e rede bloqueada; nao usar apenas cobertura agregada como
evidencia das garantias criticas.

## Verificacoes independentes aprovadas

- o merge-base da baseline e do candidato coincide com
  `3e4fcfb064fbee350d3df131b2946974c8557098`;
- o dependency head `3558ca30a5652be320feb3f28ab46a350ae9cad7`
  e ancestral da baseline e do candidato;
- o carrier altera exclusivamente `project/handoffs/phase-06.json`;
- os runs `31756127273` e `31756306732` foram consultados e confirmados como
  `success` nos SHAs material e carrier exatos;
- `validate-all`, secret scan, independence scan, Ruff, Django check,
  `git diff --check` e topologia Celery passaram localmente;
- migrations aplicaram desde PostgreSQL vazio e o rollback/reapply de
  Messaging passou no Compose;
- suite PostgreSQL local: 386 passed, 5 skipped; os skips sao os testes de
  baseline que dependem do `.git` ausente na imagem;
- nenhum provider, sandbox, secret, deploy, Flowlog runtime ou efeito externo
  foi acessado durante este Review.

## Riscos residuais e escopo corretamente bloqueado

- Evolution linked-device continua nao oficial e sem ativacao real;
- Meta e SES/SNS callbacks permanecem fail-closed sem autenticidade completa;
- adapters reais, secrets, pairing, sandbox, recipients, DNS, webhook publico
  e producao permanecem fora deste checkpoint;
- as fixtures atuais comprovam formatos outbound offline, nao homologacao com
  providers reais.

## Conclusao

O parecer e `CHANGES_REQUESTED`. Os achados P06-R01 a P06-R05 precisam de
remediacao material, testes e novo CI. Depois disso, outro Review independente
deve revalidar o candidato. QA/Security permanece bloqueado.
