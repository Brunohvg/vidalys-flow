# Review independente 03 — Fase 05 Payments

- resultado: `CHANGES_REQUESTED`;
- checkpoint: Review independente, sem correção de código;
- branch: `phase/05-payments`;
- candidato material revisado: `ff434938179670ac8a23102dd7b4cceb45dec7a9`;
- baseline (`actual_base_sha`): `4fd3a9259e9e2f31acdab44f13499eade79ab59e`;
- dependência aprovada: `888685886d7a17c6eeb008674be86656e4f6fa40`;
- carrier observado: `650d01eaf0eddbf74c5f3a1a94f948bf6ef3cb4e`;
- CI material verificado: run `31290039417`, sucesso no SHA exato;
- verificação local: 268 testes aprovados, nenhum skip e cobertura exata de
  85,0115%, acima do gate de 85%;
- QA/Segurança: bloqueado até remediação, novo SHA material, novo CI e novo
  Review independente.

## Fronteira reproduzível e revalidação dos Reviews anteriores

O merge-base entre baseline e candidato é exatamente
`4fd3a9259e9e2f31acdab44f13499eade79ab59e`; a dependência aprovada é ancestral
da baseline e do candidato. O intervalo entre o candidato material e o carrier
altera exclusivamente `project/handoffs/phase-05.json`. O GitHub Actions run
`31290039417` concluiu com sucesso no SHA material exato e incluiu PostgreSQL
17, migrations desde banco vazio, rollback/reaplicação de Payments, testes,
cobertura, scanners, Docker e Compose.

Os itens P05-R10 a P05-R17 do Review 02 estão materialmente endereçados nos
caminhos que aquele parecer descreveu: o dispatch revalida elegibilidade e
preserva retorno externo após mudança de contexto; o lease é de 90 segundos;
há backoff persistente e isolamento por item; falha conclusiva, cancelamento e
reabertura/troca explícita existem; autorização precede I/O de reconciliação;
há testes diretos adicionais; o carrier está regular; e a cobertura foi
registrada com precisão. Esta revisão encontrou novos bloqueadores nos fluxos
de cancelamento e na superfície administrativa.

## Achados bloqueadores

### P05-R18 — Crítica — evento antigo de cancelamento pode cancelar um checkout posterior de outro provider

**Evidência:** `request_hosted_checkout_cancellation` cria o outbox
`payment.checkout_cancellation_requested` apenas com o `PaymentIntent` como
aggregate e payload canônico sem correlação com o attempt
(`apps/payments/services.py:828-879`). O worker consulta todos os eventos desse
tipo sem filtrar ou mudar `OutboxEvent.status`; para cada evento, seleciona o
attempt aberto mais recente do intent, não o attempt que originou o comando
(`apps/payments/tasks.py:65-102`). Após o primeiro cancelamento verificado, o
evento deixa temporariamente de ser elegível somente porque não existe attempt
aberto. Se o gerente reabrir o intent e solicitar novo checkout — inclusive em
outro provider — o mesmo evento antigo volta a casar e dispara
`adapter.cancel_checkout` contra o recurso novo, sem comando de cancelamento
para ele.

O cenário foi confirmado por inspeção do estado persistido e do fluxo já
coberto parcialmente por `test_cancel_verified_then_explicitly_reopen_and_switch_provider`:
o teste para após criar o segundo attempt e não executa novamente o worker. O
worker também não usa `mark_attempt`, `mark_success` ou receipt próprio para
consumir o evento, ao contrário do mecanismo de outbox em
`apps/platform/services.py:41-69`.

**Impacto:** um pedido de cancelamento já satisfeito pode encerrar um link
posterior e potencialmente de outro provider. Isso viola escolha humana
explícita, idempotência, troca sem fallback e correlação de efeito externo; a
ação financeira pode ocorrer sem autorização referente ao recurso atual.

**Recomendação:** tornar o trabalho de cancelamento uma operação persistida e
correlacionada imutavelmente ao `PaymentAttempt`/recurso original, consumir ou
marcar terminalmente o evento após sucesso e impedir que eventos antigos
sejam resolvidos contra attempts futuros. Comprovar em PostgreSQL cancelamento
→ fechamento → reabertura → troca de provider → nova execução do beat, além de
dois workers concorrentes sobre o mesmo evento.

### P05-R19 — Alta — resposta autoritativa de cancelamento paga ou inconsistente é descartada

**Evidência:** `apply_verified_checkout_cancellation` mapeia o estado retornado
pelo provider e aceita somente `cancelled` ou `expired`; qualquer `paid`,
`processing`, estado desconhecido ou divergência é rejeitado antes de chamar
`_apply_resource_to_locked_attempt` (`apps/payments/services.py:921-944`). O
dispatcher captura a exceção, libera o lease e agenda retry, mantendo o intent
e o attempt no estado anterior (`apps/payments/services.py:979-1008`). Assim,
um retorno autoritativo `approved`/`paid` não marca pagamento, e valor ou moeda
divergentes não chegam a `requires_attention`.

**Impacto:** a resposta à tentativa de cancelamento pode ser a primeira
evidência conclusiva de que o cliente pagou ou de que existe inconsistência
financeira. Descartá-la mantém o sistema exibindo link aberto/aguardando e pode
repetir cancelamentos, contrariando a regra de que evidência verificada de
valor, moeda e pagamento deve atualizar ou bloquear com segurança o agregado.

**Recomendação:** aplicar toda resposta autoritativa correlacionada pela
máquina canônica antes de decidir se o cancelamento concluiu. `paid` deve ser
preservado como pagamento (e conflito com Order cancelado deve ir para atenção
conforme contrato); divergência de valor/moeda ou estado incompatível deve ir
para `requires_attention`; apenas ausência transitória de confirmação deve
usar retry. Adicionar testes diretos para paid, processing, mismatch, estado
desconhecido e corrida callback versus cancelamento.

### P05-R20 — Alta — admin não exige manager tier para evidência financeira

**Evidência:** `ReadOnlyPaymentAdmin.get_queryset` deriva e filtra a
Organization ativa, mas não verifica o papel da Membership
(`apps/payments/admin.py:14-23`). Todos os seis modelos são registrados nessa
classe. Um usuário `is_staff` com Membership OPERATOR e permissão de view — ou
um superuser operacional nessa Membership — pode abrir `PaymentAttempt`,
`PaymentProviderAccount`, `PaymentWebhookReceipt` e `PaymentCommandReceipt`.
Como não há `exclude`, `readonly_fields` seletivo ou negação de
`has_view_permission`, a tela expõe URL hospedada, identificador externo,
alias de credencial e evidências que o manifesto reserva exclusivamente a
OWNER, ADMIN e MANAGER. O teste novo verifica apenas isolamento entre duas
Organizations para um MANAGER (`apps/payments/tests/test_remediation.py:437-458`),
não a autorização por papel.

**Impacto:** a interface administrativa contorna o masking da aplicação e
expõe metadados financeiros/provider ao OPERATOR, quebrando o contrato de
autorização e privacidade apesar do isolamento de tenant.

**Recomendação:** negar view administrativa de modelos/evidências de Payments
sem Membership ativa manager tier na Organization selecionada, mantendo o
queryset tenant-scoped, e adicionar testes de OPERATOR staff, Membership
inativa, ausência de Organization ativa e cross-tenant para changelist e
object view.

## Achado adicional

### P05-R21 — Baixa — documentação de checkpoint ficou temporalmente desatualizada

**Evidência:** `docs/PROJECT_STATUS.md` e
`docs/ROADMAP_TO_PRODUCTION.md` ainda afirmam que o CI do SHA material precisa
ser executado, embora o run `31290039417` esteja verde e corretamente
registrado no handoff. `docs/domains/PAYMENTS_VISION.md` ainda descreve apenas
o primeiro Review como mudanças solicitadas.

**Impacto:** não muda o comportamento do domínio, mas prejudica a retomada por
clone e a leitura inequívoca do checkpoint atual.

**Recomendação:** na próxima remediação material, alinhar os documentos ao
Review 03 e ao CI já verificado, sem antecipar QA ou aprovação humana.

## Escopo, arquitetura, dinheiro e estados

- O diff material permanece dentro de Payments e dos contratos unidirecionais
  permitidos; não há Appmax, Messaging, refund, deploy, SDK novo ou código do
  Flowlog.
- `PaymentIntent` preserva BRL e `Decimal(14,2)` a partir de `Order.total`; os
  snapshots são protegidos por model, QuerySet e trigger PostgreSQL.
- A constraint de um attempt `requested`/`active`/`processing`, a ordem de
  locks `Order → PaymentIntent → PaymentAttempt`, `expected_version`, receipts
  de comando e histórico separado permanecem presentes.
- As transições de callback são monotônicas, `requires_attention` fica
  protegido de callback e falha conclusiva fecha o attempt. Os achados R18 e
  R19 impedem considerar correto o subfluxo de cancelamento/troca.

## Provider rollout, webhook e segurança

- Mercado Pago Checkout Pro e Pagar.me Payment Links continuam atrás de
  adapters com efeitos externos desabilitados; Appmax permanece ausente.
- Mercado Pago valida assinatura e janela, deduplica por recurso/request ID
  autenticado, consulta recurso autoritativo injetado e não persiste callback
  bruto. Pagar.me callback permanece bloqueado por código e constraint.
- O fixture autouse bloqueia DNS para hosts conhecidos de Mercado Pago e
  Pagar.me nos testes de Payments; nenhum provider, sandbox, secret ou efeito
  externo foi acessado nesta revisão.
- AuditEvent e OutboxEvent usam allowlist canônica; raw callback, URL hospedada
  e identificadores externos não foram observados nesses payloads.

## Autorização, privacidade e isolamento organizacional

Services e selectors humanos derivam Organization de Membership ativa e os
workers correlacionam Organization. Reconciliação valida ator, tenant, conta e
adapter antes do fetch. OPERATOR é mascarado nas telas normais. O isolamento
administrativo por Organization passou, mas P05-R20 demonstra que esse
queryset não substitui a autorização manager tier exigida para evidência.

## Migrations, testes e gates

- `validate-all`: passou;
- secret scan e independence scan: passaram;
- Ruff: passou;
- Django system check: passou;
- migration consistency: sem mudanças detectadas;
- suite local PostgreSQL: 268 testes aprovados, zero skips;
- cobertura local: 85,01152959262106% (`85%` exibido), acima do mínimo;
- CI material: run `31290039417`, `success` no SHA exato, com PostgreSQL 17,
  banco vazio, rollback/reaplicação, Docker e Compose;
- `git diff --check` do material: passou;
- carrier: altera exclusivamente `project/handoffs/phase-05.json`;
- os testes novos cobrem a maior parte da remediação anterior, mas não cobrem
  evento antigo contra attempt novo, resposta paga no cancelamento nem
  autorização OPERATOR no admin.

## Riscos e itens adiados

Pagar.me callback, credenciais, sandbox, webhook público, observabilidade de
produção, cobrança real e deploy permanecem corretamente adiados. A cobertura
agregada está apenas 0,01 ponto percentual acima do gate e não compensa os
caminhos financeiros sem teste direto. Appmax, pagamentos parciais, split,
multi-moeda, refund, disputas, taxas, settlement, Messaging e fases posteriores
continuam fora do escopo.

## Decisões humanas ainda necessárias

Este parecer não aprova produto, QA, sandbox, provider, PR, merge, release,
deploy ou fase posterior. A decisão humana imediata é somente autorizar ou não
uma nova remediação dos achados P05-R18 a P05-R21. Se autorizada, ela deve gerar
novo SHA material, CI no SHA exato, carrier exclusivo do handoff e quarto
Review independente antes de QA/Segurança.

## Parecer

`CHANGES_REQUESTED`. P05-R18 permite efeito externo de cancelamento sem comando
correspondente ao checkout atual; P05-R19 pode perder evidência autoritativa de
pagamento ou inconsistência; P05-R20 viola a autorização manager-only da
superfície administrativa. Nenhum código foi corrigido nesta revisão.
