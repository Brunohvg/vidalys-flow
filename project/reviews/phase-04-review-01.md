# Review independente 01 — Fase 04 Fulfillment

- resultado: `CHANGES_REQUESTED`;
- candidato material revisado: `173d0cca7da7a5b8ca9103dbd11a3e13168d18a2`;
- carrier de evidência observado: `e1f4af0066b597556ff16d1a87f6c44d57f09195`;
- CI registrado: run `31252778133`, sucesso, 201 testes e 85% de cobertura;
- QA/Segurança: bloqueado até remediação, novo CI e novo Review independente.

## Achados bloqueadores

1. **Alta — ordem inversa de locks permite deadlock entre transição e
   cancelamento por evento.** `transition_fulfillment` bloqueia primeiro o
   `Fulfillment` e depois o `Order`, enquanto
   `consume_order_cancelled_event` bloqueia primeiro o `Order` e depois todos
   os `Fulfillments`. Execuções concorrentes sobre o mesmo lote podem formar o
   ciclo `Fulfillment -> Order` / `Order -> Fulfillment`. A implementação deve
   adotar uma única ordem determinística e comprová-la em PostgreSQL.

2. **Alta — o gate obrigatório de concorrência não está coberto.** A suíte
   possui somente um teste concorrente, para duas criações que disputam a
   quantidade do mesmo item. Não há testes concorrentes diretos para edição de
   alocação, transição, cancelamento manual versus transição, nem cancelamento
   do Order/evento versus avanço do lote. Isso não satisfaz o manifesto, que
   exige concorrência de criação, alocação, transição e cancelamento.

3. **Média — isolamento e sanitização obrigatórios não possuem toda a
   evidência direta exigida.** Não há teste cross-organization específico do
   consumidor de `order.cancelled`. A sanitização testa snapshots em
   audit/outbox e o motivo comercial em AuditEvent, mas não comprova
   diretamente ausência de PII e texto livre em logs, exceptions, receipts e
   no outbox de cancelamento, como exige o manifesto.

4. **Média — o carrier viola o protocolo de handoff.** O intervalo
   `173d0cca..e1f4af0` altera `docs/PROJECT_STATUS.md` e
   `project/roadmap.json`, além de `project/handoffs/phase-04.json`. O protocolo
   determina que o commit posterior ao SHA material altere somente o handoff.
   A evidência deve ser regularizada sem reescrever histórico destrutivamente.

## Verificações executadas

- governança (`validate-all`): passou;
- secret scan: passou;
- independence scan: passou;
- Ruff: passou;
- Django system check: passou;
- migration consistency: sem mudanças detectadas, com aviso de PostgreSQL
  indisponível;
- suíte PostgreSQL local: não executável neste ambiente porque não há daemon
  Docker nem PostgreSQL em `127.0.0.1:5432`; o resultado de CI acima permanece
  como evidência registrada do candidato, mas não supre os casos ausentes.

Este relatório registra achados e não corrige o candidato. Não aprova produto,
QA, PR, merge, release, deploy nem início da Fase 05. A remediação deve gerar
novo SHA material, novo CI, handoff atualizado e novo Review independente.
