# Review independente 01 — Fase 05 Payments

- resultado: `CHANGES_REQUESTED`;
- candidato material revisado: `707401a13a4cd493409e6258301a1aaa22cba68b`;
- baseline: `4fd3a9259e9e2f31acdab44f13499eade79ab59e`;
- carrier de handoff observado: `d2a793431a968df5c8e2520a1c6a51f34acd2ef9`;
- CI registrado no handoff: run `31287810333`, sucesso no candidato material;
- verificacao local: 240 testes aprovados, nenhum skip e cobertura total de
  85%; 33 testes diretos de Payments aprovados;
- QA/Seguranca: bloqueado ate remediacao, novo CI e novo Review independente.

## Achados bloqueadores

### P05-R01 — Alta — envio externo nao possui lease nem consumidor assincrono

**Evidencia:** `apps/payments/services.py:257-275` consulta um attempt
`requested` sem lock ou claim persistente, executa `adapter.create_checkout`
e somente depois tenta ativa-lo. `apps/payments/tasks.py:1-32` implementa
apenas o consumo de `order.cancelled`; nao existe task que consuma o outbox de
`payment.checkout_requested` ou despache attempts. Isso diverge dos requisitos
de outbox, lease e retry de `project/phases/05-payments.json:123-126` e
`project/phases/05-payments.json:183-189`.

**Impacto:** apos ativacao futura do adapter, dois workers podem observar o
mesmo attempt e chamar o provider simultaneamente. A chave estavel reduz risco
somente se o endpoint remoto honrar a mesma semantica; ela nao substitui o
lease local exigido. No estado atual, o fluxo normal tambem nao possui caminho
assincrono que transforme a solicitacao persistida em checkout ativo.

**Recomendacao:** implementar claim/lease transacional com expiracao, retry e
ordem de locks deterministica, ligar o evento do outbox a uma task registrada
e comprovar concorrencia de dois dispatchers e timeout apos sucesso remoto em
PostgreSQL, sempre com adapter fake e sem rede.

### P05-R02 — Alta — maquina de estados permite regressoes e saida automatica de `requires_attention`

**Evidencia:** `apps/payments/services.py:388-408` considera nao monotona apenas
uma divergencia depois de `paid`, `cancelled` ou `expired`. Assim, um callback
`pending` posterior a `processing` regride o intent para `awaiting_payment`.
Como `requires_attention` nao pertence ao conjunto terminal de
`apps/payments/services.py:43-47`, qualquer callback posterior tambem pode
retirar o intent da excecao sem reconciliacao gerencial. O contrato determina
que somente comando de reconciliacao verificado pode resolver esse estado e
que transicoes devem ser monotonicas em
`project/phases/05-payments.json:160-166` e
`project/phases/05-payments.json:187-189`.

**Impacto:** callbacks fora de ordem podem ocultar processamento em andamento,
e uma divergencia financeira previamente sinalizada pode desaparecer sem
decisao operacional. Isso compromete a confiabilidade do estado canonico de
pagamento.

**Recomendacao:** definir tabela explicita de transicoes por origem, impedir
regressoes entre estados nao terminais e bloquear qualquer saida de
`requires_attention` no caminho de callback. Cobrir `processing -> pending`,
divergencia seguida de callback e resolucao exclusiva por reconciliacao.

### P05-R03 — Alta — deduplicacao de callback usa identificador nao coberto pela assinatura

**Evidencia:** `apps/payments/callbacks.py:77-89` extrai `payload["id"]` como
identificador do evento, mas a assinatura validada cobre somente `data.id`,
`X-Request-Id` e timestamp. `apps/payments/models.py:327-333` e
`apps/payments/services.py:426-431` deduplicam exclusivamente pelo ID superior
do payload. `X-Request-Id` nao e persistido nem participa de uma constraint de
replay.

**Impacto:** durante a janela valida, um callback capturado pode ser reenviado
com IDs superiores diferentes sem invalidar a assinatura. Cada variacao
contorna a deduplicacao, provoca nova consulta autoritativa e cria novo
receipt; valores excessivamente longos ainda podem terminar em erro de banco
na rota publica. O rate limit por IP nao corrige replay distribuido.

**Recomendacao:** deduplicar por um identificador autenticado e documentado,
como digest canonico de conta, recurso e request ID assinado, com tamanho e
formato validados antes de I/O. Adicionar testes de replay com mesmo request ID
e evento superior alterado, tamanhos extremos e concorrencia do mesmo callback.

### P05-R04 — Alta — snapshot monetario declarado imutavel pode ser reescrito

**Evidencia:** `PaymentIntent.amount` e `currency` sao campos comuns em
`apps/payments/models.py:72-78`. O manager customizado em
`apps/payments/models.py:7-9` bloqueia apenas `delete`; `save`, `update` e
`bulk_update` continuam permitindo alterar valor, moeda e snapshots depois da
criacao. O handoff declara snapshot imutavel em
`project/handoffs/phase-05.json:27-30`, e o contrato repete a garantia em
`docs/domains/PAYMENTS.md:23-37`.

**Impacto:** uma chamada interna, comando de manutencao ou regressao futura
pode reescrever a evidencia financeira sem criar historia, mudar versao ou
gerar audit/outbox. Isso quebra a rastreabilidade do valor cobrado.

**Recomendacao:** proteger campos imutaveis no modelo e nos caminhos de update,
preferencialmente com defesa persistente proporcional ao risco, e adicionar
testes diretos de `save`, `QuerySet.update` e `bulk_update` apos a criacao e
apos `paid`.

### P05-R05 — Alta — matriz obrigatoria de testes nao foi entregue

**Evidencia:** `apps/payments/tests/test_concurrency.py:14-58` contem somente a
disputa entre duas solicitacoes locais de checkout. Nao ha teste concorrente
direto para criacao, dispatch, callback, reconciliacao ou cancelamento de
Order; tambem nao ha caso de timeout apos sucesso no provider. Os supostos
testes de contrato em
`apps/payments/tests/test_providers_and_tasks.py:31-79` apenas constroem o
payload local e verificam as mesmas chaves produzidas, sem fixtures oficiais
independentes. Isso nao satisfaz
`project/phases/05-payments.json:222-235`, embora o handoff registre
`concurrency: passed` e contratos aprovados em
`project/handoffs/phase-05.json:48-59` e
`project/handoffs/phase-05.json:82-88`.

**Impacto:** o CI verde e os 85% agregados nao exercitam justamente os riscos
financeiros e de corrida mais importantes. Os defeitos P05-R01 a P05-R03
passam pela suite atual, e os builders nao possuem evidencia reproduzivel de
aderencia ao contrato oficial dos providers.

**Recomendacao:** completar toda a matriz enumerada no manifesto, usar
fixtures de request/response versionadas e derivadas do contrato oficial, e
executar corridas reais em PostgreSQL com assertiva de ausencia de deadlock,
duplicidade e regressao de estado.

### P05-R06 — Alta — ordem de locks pode formar deadlock

**Evidencia:** `request_hosted_checkout` bloqueia `Order -> PaymentIntent ->
PaymentProviderAccount` em `apps/payments/services.py:207-224`. O callback
bloqueia `PaymentProviderAccount -> Order -> PaymentIntent -> PaymentAttempt`
em `apps/payments/services.py:411-448`.

**Impacto:** solicitacao e callback concorrentes para a mesma conta/pedido
podem formar o ciclo em que uma transacao aguarda a conta e a outra aguarda o
Order. A rota publica nao captura `OperationalError`, podendo responder 500 e
depender de retry externo nao comprovado.

**Recomendacao:** uniformizar uma unica ordem global de locks, documenta-la e
comprova-la com teste PostgreSQL que execute callback, request, reconciliacao e
cancelamento concorrentes.

## Achados adicionais

### P05-R07 — Media — busca do OPERATOR funciona como oraculo de nome do cliente

**Evidencia:** `apps/payments/selectors.py:11-20` sempre pesquisa
`customer_name_snapshot`, sem considerar o papel. A listagem e permitida ao
OPERATOR por `apps/payments/policies.py:11-17`, apesar de o detalhe mascarar o
nome em `apps/payments/selectors.py:47-50`.

**Impacto:** um OPERATOR pode testar nomes e inferir quais clientes possuem
pagamentos, mesmo sem receber o nome diretamente na tela.

**Recomendacao:** tornar a busca sensivel ao papel, limitando OPERATOR a
campos nao pessoais, e adicionar teste negativo de inferencia por filtro.

### P05-R08 — Media — payloads internos excedem o schema minimo aprovado

**Evidencia:** o manifesto limita AuditEvent e OutboxEvent a IDs canonicos,
estado, valor, moeda, versao e flags booleanas em
`project/phases/05-payments.json:176-181`. Entretanto,
`apps/payments/services.py:237-251` inclui provider, attempt ID e
`amount_minor`, e `apps/payments/services.py:464-470` inclui `reason_code` em
AuditEvent.

**Impacto:** os valores atuais sao controlados e nao constituem PII observada,
mas o schema implementado e mais amplo que o aprovado e facilita expansao
silenciosa de evidencia operacional.

**Recomendacao:** alinhar payloads ao schema fechado aprovado ou obter decisao
humana explicita para o schema ampliado, com testes de allowlist de chaves.

### P05-R09 — Baixa — inconsistencias documentais e de higiene do diff

**Evidencia:** `project/phases/05-payments.json:168-177` menciona
`Order.grand_total`, enquanto o modelo e a implementacao usam `Order.total` em
`apps/payments/services.py:164-172` e `docs/domains/PAYMENTS.md:61-68`.
`git diff --check` tambem aponta linha em branco adicional no fim dos tres
templates de Payments.

**Impacto:** a divergencia dificulta auditoria automatizada do contrato; o
whitespace e apenas higiene.

**Recomendacao:** escolher o nome canonico real do total e uniformizar
manifesto, documentacao e testes; normalizar os templates.

## Verificacoes executadas

- ancestralidade: o merge-base entre baseline e candidato coincide com
  `4fd3a9259e9e2f31acdab44f13499eade79ab59e`;
- commits materiais: `6406547`, `7a0aeb7`, `3ec9c49` e `707401a`;
- governanca (`validate-all`): passou;
- secret scan: passou;
- independence scan: passou;
- Ruff: passou;
- Django system check: passou;
- migration consistency: sem mudancas detectadas;
- suite PostgreSQL local: 240 testes aprovados, zero skips;
- cobertura local: 85%, atendendo o minimo agregado;
- testes diretos de Payments: 33 aprovados;
- `git diff --check`: falhou somente pelas tres linhas em branco descritas em
  P05-R09;
- nenhuma chamada de provider, sandbox ou outro efeito externo foi realizada;
- o relatorio foi submetido aos scanners de secrets e independencia.

## Parecer

O candidato nao esta apto a avancar para QA/Seguranca. Os achados altos afetam
concorrencia, idempotencia externa, replay de callbacks, integridade monetaria,
maquina de estados e a evidencia dos gates obrigatorios. A remediacao deve
produzir novo SHA material, CI no SHA exato, handoff atualizado e novo Review
independente.

Este parecer nao altera status oficial e nao autoriza produto, sandbox,
provider, PR, merge, release, deploy ou inicio de fase posterior.
