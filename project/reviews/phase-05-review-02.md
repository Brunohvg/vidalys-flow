# Review independente 02 — Fase 05 Payments

- resultado: `CHANGES_REQUESTED`;
- candidato material revisado: `0ca4ae6d4db782e66d5636fd3374033621d4418a`;
- baseline: `4fd3a9259e9e2f31acdab44f13499eade79ab59e`;
- carrier observado: `c8800fff9ab3d381b3460472b512f15161bf46f1`;
- CI material verificado: run `31288840331`, sucesso no SHA exato;
- verificacao local: 257 testes aprovados, nenhum skip e cobertura real de
  85,46%, acima do gate de 85%;
- QA/Seguranca: bloqueado ate remediacao, novo CI e novo Review independente.

## Revalidacao dos achados do Review 01

| Achado | Resultado | Evidencia resumida |
| --- | --- | --- |
| P05-R01 | parcial, ainda bloqueante | worker, rota e lease existem, mas o claim nao revalida Order, intent ou conta e o lease expira antes do limite da task |
| P05-R02 | parcial, ainda bloqueante | regressoes e saida por callback foram bloqueadas, mas `failed` ficou inalcançavel e nao existe fechamento/cancelamento para retry ou troca de provider |
| P05-R03 | resolvido | replay usa recurso e digest do `X-Request-Id` autenticado, com constraint e teste de ID superior alterado |
| P05-R04 | resolvido | ORM e trigger PostgreSQL protegem Organization, Order, moeda, valor e snapshots |
| P05-R05 | nao resolvido | a suite cresceu, mas ainda omite corridas e superficies exigidas e nao detecta os defeitos deste Review |
| P05-R06 | resolvido | os caminhos mutaveis observados adotam `Order -> PaymentIntent -> PaymentAttempt`, sem lock anterior da conta |
| P05-R07 | resolvido | busca por nome ficou restrita ao manager tier e possui teste negativo para OPERATOR |
| P05-R08 | resolvido | AuditEvent e OutboxEvent possuem allowlist executavel e flags booleanas |
| P05-R09 | resolvido no material | `Order.total` foi uniformizado e `git diff --check` passa no candidato |

## Achados bloqueadores

### P05-R10 — Critica — worker pode criar checkout para Order cancelado ou conta desativada e descartar o resultado remoto

**Evidencia:** `claim_requested_checkout` em
`apps/payments/services.py:282-311` bloqueia Order, intent e attempt, mas valida
somente que o attempt permanece `requested`. Nao revalida
`Order.status == confirmed`, `PaymentIntent.status == pending` nem
`PaymentProviderAccount.is_active`. O cancelamento em
`apps/payments/services.py:686-745` move o intent para `requires_attention`,
mas preserva o attempt como `requested`. Portanto, o worker ainda pode chamar
`adapter.create_checkout` em `apps/payments/services.py:330-349`. Depois da
criacao externa, `activate_hosted_checkout` rejeita o Order cancelado em
`apps/payments/services.py:370-388`, e o bloco de erro libera o lease sem
persistir o ID ou a URL retornados.

**Impacto:** um checkout pagavel pode ser criado depois do cancelamento e sua
existencia ficar ausente da evidencia local. Beats posteriores voltam a
tentar o mesmo trabalho. Desativar uma conta entre solicitacao e dispatch
tambem nao impede o uso futuro de sua credencial. Isso viola elegibilidade,
surfaceamento de risco e coordenacao segura com Orders.

**Recomendacao:** revalidar Order, intent, attempt, Organization e conta sob a
ordem global de locks antes de adquirir o lease e antes de I/O. Definir um
caminho seguro para o caso em que o Order muda durante a chamada: preservar a
evidencia externa sanitizada, colocar o agregado em `requires_attention` e
nunca perder um recurso potencialmente pagavel. Cobrir cancelamento e
desativacao antes, durante e depois do dispatch em PostgreSQL.

### P05-R11 — Alta — duracao do lease nao cobre a duracao maxima da task

**Evidencia:** `DISPATCH_LEASE_SECONDS` vale 45 segundos em
`apps/payments/services.py:50`, enquanto `CELERY_TASK_SOFT_TIME_LIMIT` vale 50
e `CELERY_TASK_TIME_LIMIT` vale 60 em `config/settings/base.py:117-120`. Nao ha
heartbeat ou renovacao de lease durante `adapter.create_checkout`.

**Impacto:** entre 45 e 60 segundos, outro worker pode tomar o lease expirado
e iniciar uma segunda chamada enquanto o primeiro ainda executa. A chave de
idempotencia do provider e defesa adicional, mas nao satisfaz a garantia local
de que dois dispatchers nao chamam simultaneamente.

**Recomendacao:** tornar o lease maior que o pior limite de execucao com
margem de clock/infraestrutura ou implementar renovacao atomica; adicionar
teste com relogio controlado que atravesse o limite atual e comprove uma unica
chamada externa.

### P05-R12 — Alta — estado `failed`, cancelamento explicito e troca de provider ficaram sem caminho funcional

**Evidencia:** `map_provider_status` ainda mapeia rejeicoes para `failed` em
`apps/payments/providers.py:48-71`, mas
`apps/payments/services.py:478-510` converte todo target `failed` para
`requires_attention`. Assim, o ramo que grava `PaymentAttempt.Status.FAILED`
em `apps/payments/services.py:428-446` tornou-se inalcançavel. O proprio teste
`apps/payments/tests/test_services.py:443-481`, apesar do nome afirmar retry
explicito, agora comprova que retry e bloqueado. Nao existe service, view ou
task de cancelamento explicito de link em `apps/payments/`, embora o manifesto
autorize cancelamento gerencial e troca verificada de provider em
`project/phases/05-payments.json:165-166` e
`project/phases/05-payments.json:207-213`.

**Impacto:** uma rejeicao autoritativa prende o intent em atencao sem comando
capaz de fechar a tentativa, marcar `failed`, voltar a um estado elegivel ou
trocar de provider. Um manager tambem nao consegue cancelar um link ativo. A
maquina persistida anuncia estados e operacoes que o dominio nao executa.

**Recomendacao:** formalizar, dentro das decisoes ja aprovadas, a transicao de
falha conclusiva e o comando idempotente de fechamento/cancelamento. Exigir
confirmacao verificada do fechamento antes de retry ou troca, preservar
`requires_attention` para inconsistencias reais e adicionar expected_version,
locks, history, audit/outbox e testes de autorizacao/concorrencia.

### P05-R13 — Alta — worker nao oferece retry isolado e pode bloquear o lote

**Evidencia:** `dispatch_checkout_events` captura somente
`PaymentDomainError` em `apps/payments/tasks.py:18-52`. Um timeout ou erro de
transporte e relancado por `dispatch_requested_checkout` e interrompe todo o
lote. Alem disso, `require_external_effects_allowed` lanca
`ExternalEffectBlockedError` (`apps/platform/guardrails.py:6-16`), que nao e
subclasse de `PaymentDomainError`; no ambiente bloqueado padrao, o primeiro
evento solicitado faz a task falhar em vez de encerrar de forma controlada.
Nao ha `autoretry_for`, retry Celery ou isolamento por evento.

**Impacto:** um attempt antigo com falha repetida impede o processamento dos
eventos seguintes selecionados. O beat recorrente pode repetir o mesmo erro e
gerar starvation e ruido operacional, sem evidenciar resultado canonico.

**Recomendacao:** tratar por evento as categorias esperadas de bloqueio,
timeout e transporte, manter logs/metricas sanitizados e retry com backoff e
mesma chave. Um evento falho nao deve abortar os demais. Testar lote misto,
efeitos bloqueados e erro permanente/transitorio.

### P05-R14 — Alta — matriz normativa de testes continua incompleta

**Evidencia:** os novos testes cobrem criacao, dois dispatchers imediatos,
callback duplicado e callback/reconciliacao/cancelamento. Entretanto, nao ha
teste de dispatch concorrente com cancelamento do Order, lease atravessando o
time limit, conta desativada antes de I/O, provider switch, cancelamento de
link, lote com falha, worker cross-Organization ou inactive Membership. A
administracao continua testada apenas quanto a registro/read-only em
`tests/test_domain_admin.py`, sem isolamento organizacional direto. Tambem nao
ha bloqueio executavel de rede na suite; o teste apenas usa adapters locais.
Essas lacunas conflitam com `project/phases/05-payments.json:222-235` e com a
regra de teste direto de toda superficie em
`project/phases/05-payments.json:207-213`.

**Impacto:** os 257 testes e a cobertura agregada verde nao exercitam os
cenarios que revelam P05-R10 a P05-R13. O handoff afirma concorrencia e matriz
completas sem evidencia suficiente.

**Recomendacao:** completar a matriz literal do manifesto, incluindo workers,
admin, inactive Membership, cross-tenant, cancelamento/troca e todas as
corridas externas simuladas. CI deve bloquear rede de forma executavel, nao
apenas depender de os testes atuais nao a chamarem.

### P05-R15 — Media bloqueante de governanca — carrier viola o protocolo de handoff

**Evidencia:** o intervalo
`0ca4ae6d4db782e66d5636fd3374033621d4418a..c8800fff9ab3d381b3460472b512f15161bf46f1`
altera `docs/CLONE_AND_CONTINUE.md`, `docs/PROJECT_STATUS.md`,
`docs/ROADMAP_TO_PRODUCTION.md`, `project/phases/05-payments.json` e o handoff.
O manifesto muda `implementation_status` e `review_status`. O protocolo em
`docs/agents/HANDOFF_PROTOCOL.md:24-30` permite que o carrier posterior ao
`head_sha` altere exclusivamente o arquivo de handoff.

**Impacto:** parte da evidencia e do estado do checkpoint nao pertence ao SHA
material que recebeu CI, contrariando a fronteira reproduzivel entre candidato
e carrier.

**Recomendacao:** regularizar sem reescrever historico: produzir novo SHA
material que inclua toda mudanca necessaria fora do handoff, executar CI nesse
SHA e criar depois um carrier que altere somente
`project/handoffs/phase-05.json`.

## Achados adicionais

### P05-R16 — Media — reconciliacao pode realizar I/O antes de autorizar e revalidar o tenant

**Evidencia:** `fetch_and_reconcile` seleciona o attempt diretamente pelo
objeto recebido, verifica o guardrail e executa `adapter.fetch_resource` em
`apps/payments/services.py:667-675`. Somente depois
`reconcile_verified_resource` chama `_require_manager` e revalida Organization
em `apps/payments/services.py:603-636`.

**Impacto:** quando efeitos externos forem habilitados, um chamador interno
nao autorizado ou com intent de outro tenant pode provocar consulta ao
provider antes da rejeicao. Nao ha view publica atual para esse comando, mas o
service contradiz a defesa de autorizacao no limite de I/O.

**Recomendacao:** autorizar e revalidar Organization, intent, account e
adapter antes do fetch, preservando I/O fora da transacao de aplicacao, e
adicionar testes de OPERATOR, Membership inativa e cross-Organization que
confirmem zero chamadas ao adapter.

### P05-R17 — Baixa documental — cobertura do handoff foi arredondada para cima

**Evidencia:** o handoff registra 86% em
`project/handoffs/phase-05.json:48-60`. A execucao local do mesmo candidato
produziu 85,45865898807075%, exibido como 85% pela configuracao atual do
Coverage.

**Impacto:** o gate de 85% continua atendido, mas a evidencia nao usa a mesma
semantica de exibicao reproduzivel.

**Recomendacao:** registrar o valor exibido pelo artefato de CI ou a precisao
decimal explicita, sem alternar criterios de arredondamento.

## Verificacoes independentes

- ancestralidade: o merge-base de baseline e candidato coincide com
  `4fd3a9259e9e2f31acdab44f13499eade79ab59e`;
- dependencia: `888685886d7a17c6eeb008674be86656e4f6fa40`
  e ancestral da baseline e do candidato;
- diff material: a remediacao adiciona migration, lease, replay key, trigger,
  worker, fixtures e testes sem Appmax, Messaging, deploy ou SDK externo;
- CI GitHub: run `31288840331` consultado e confirmado `success` no SHA
  `0ca4ae6d4db782e66d5636fd3374033621d4418a`, incluindo PostgreSQL vazio,
  rollback/reaplicacao de Payments, testes, Docker e Compose;
- governanca (`validate-all`): passou;
- secret scan e independence scan: passaram;
- Ruff, Django check e migration consistency: passaram;
- `git diff --check` no candidato: passou;
- suite PostgreSQL local: 257 testes aprovados, zero skips;
- cobertura local: 85,45865898807075%, acima do minimo;
- trigger de imutabilidade foi exercitado diretamente no PostgreSQL;
- nenhum provider, sandbox, secret, deploy ou runtime Flowlog foi acessado.

## Riscos residuais apos os itens resolvidos

- a autenticidade do callback Pagar.me continua corretamente bloqueada;
- adapters reais, credenciais, sandbox, registro publico de callback e
  observabilidade operacional permanecem adiados e nao foram validados;
- as fixtures de provider sao evidencias locais datadas e precisam ser
  revalidadas antes de sandbox/producao;
- o rate limiter depende de Redis e falha fechado, conforme contrato.

## Parecer

Os achados P05-R10 a P05-R15 impedem liberar QA/Seguranca. A remediacao
resolveu replay, imutabilidade, schema de evidencia, oraculo de PII e a ordem
principal de locks, mas ainda permite efeitos externos apos cancelamento,
duplicidade durante expiracao do lease, starvation do worker e uma maquina de
estados sem os comandos aprovados de fechamento/troca.

A proxima remediacao deve gerar novo candidato material, novo CI no SHA exato,
carrier exclusivamente de handoff e novo Review independente. Este relatorio
nao altera status oficial e nao autoriza produto, provider, sandbox, QA, PR,
merge, release, deploy ou fase posterior.
