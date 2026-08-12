# Review independente 04 — Fase 05 Payments

- decisão: `APPROVED`;
- checkpoint: Review independente, sem correção de código e sem execução de
  QA/Segurança;
- branch: `phase/05-payments`;
- candidato material revisado:
  `464c2ac9af1bbeaacf0f33cccec7af5a73feb94e`;
- baseline (`actual_base_sha`):
  `4fd3a9259e9e2f31acdab44f13499eade79ab59e`;
- dependência aprovada:
  `888685886d7a17c6eeb008674be86656e4f6fa40`;
- carrier observado: `7c9ec3ec12f1da482b57ad654a86751a81ce69c5`;
- CI material: run `31556138368`, sucesso no SHA exato;
- CI do carrier: run `31556315913`, sucesso no SHA exato;
- verificação local: 275 testes PostgreSQL aprovados, nenhum skip, cobertura
  exata de 85,2363% e 68 testes diretos de Payments aprovados;
- blockers críticos, altos ou médios: nenhum.

## Fronteira reproduzível

O candidato descende da baseline e da dependência aprovada. O intervalo
`464c2ac..7c9ec3e` altera exclusivamente
`project/handoffs/phase-05.json`, conforme o protocolo de handoff. A working
tree estava limpa antes desta evidência de Review. O diff material não inclui
Appmax, Messaging, refund, deploy, SDK novo, credencial, runtime ou código do
Flowlog.

Os dois runs do GitHub Actions foram consultados diretamente. Ambos concluíram
com sucesso e executaram governança, scanners, Ruff, Django check, migrations
desde PostgreSQL 17 vazio, rollback e reaplicação de Payments, testes,
cobertura, Docker build e validação de Compose.

## Revalidação dos achados do Review 03

| Achado | Resultado | Evidência resumida |
| --- | --- | --- |
| P05-R18 | resolvido | o evento usa `payment_attempt` e o ID exato do attempt; o attempt persiste o UUID único do evento e o worker exige simultaneamente Organization, attempt e evento correlacionados; conclusão terminal impede replay contra checkout posterior |
| P05-R19 | resolvido | `paid`, `processing`, mismatch, estado desconhecido, `cancelled`, `expired` e falha passam pela máquina canônica; `processing` mantém backoff, conflitos vão para atenção e pagamento em Order cancelado preserva attempt pago |
| P05-R20 | resolvido | o admin read-only exige Organization ativa e Membership ativa OWNER, ADMIN ou MANAGER tanto no queryset quanto nas permissões de módulo e objeto; OPERATOR, tenant ausente/inativo e objeto cross-tenant são negados |
| P05-R21 | resolvido | status, roadmap, arquitetura, segurança, visão de Payments e guia de continuidade refletem a terceira remediação, seus CIs e a necessidade deste Review antes de QA |

Os testes diretos exercitam evento antigo após reabertura e troca de provider,
correlação e schema fechado, segundo cancelamento pendente, toda a matriz de
respostas autoritativas, callback concorrente antes do worker, dois workers de
cancelamento e autorização administrativa. A ordem inversa de evidência
terminal continua protegida pela regra monotônica: um fato conflitante leva o
intent a `requires_attention`, sem sobrescrever silenciosamente o estado
terminal, e deixa receipt/histórico sanitizado para reconciliação gerencial.

## Contratos, isolamento e privacidade

- dinheiro permanece BRL, `Decimal(14,2)` e derivado do `Order.total`
  persistido; os snapshots continuam protegidos no ORM e por trigger;
- a constraint PostgreSQL mantém no máximo um attempt aberto e os caminhos
  mutáveis preservam a ordem `Order → PaymentIntent → PaymentAttempt`;
- cancelamento usa lease de 90 segundos, I/O fora da transação, chave estável,
  backoff persistente e consumo terminal do trabalho correlacionado;
- services, selectors, workers, callback e admin revalidam Organization; os
  testes cross-tenant e de concorrência passaram;
- AuditEvent e OutboxEvent permanecem em schema fechado e sanitizado; URL,
  identificador externo, callback bruto, token, assinatura e PII não foram
  observados na evidência operacional;
- Mercado Pago e Pagar.me permanecem atrás de adapters com efeito externo
  bloqueado; callback Pagar.me continua bloqueado e Appmax ausente.

## Gates independentes

- `validate-all`: passou;
- baseline/governança com `origin/main`: passou;
- secret scan e independence scan: passaram;
- Ruff: passou;
- Django system check: passou;
- migration consistency: sem mudanças detectadas;
- `git diff --check`: passou;
- Compose principal e de testes: configuração válida;
- suíte PostgreSQL: 275 aprovados, zero skips;
- cobertura independente: 85,23629489603024%, acima do mínimo de 85%;
- Payments direto: 68 aprovados;
- migration `0004_paymentattempt_cancellation_correlation` aplicada desde banco
  vazio e revertida/reaplicada no CI material exato;
- nenhum provider, sandbox, secret, deploy ou runtime Flowlog foi acessado.

A cobertura local teve pequena variação em relação aos 85,39% registrados na
execução de implementação, mas ambas as medições atendem ao gate e os caminhos
financeiros críticos possuem testes comportamentais diretos. Isso permanece
como margem operacional estreita, não como blocker de Review.

## Riscos e itens adiados

Pagar.me callback, credenciais, sandbox, webhook público, observabilidade de
produção, cobrança real e deploy permanecem adiados. O rate limiter continua
dependente de Redis e falha fechado. Fixtures de provider são evidências
locais datadas e deverão ser revalidadas antes de sandbox ou produção.
Appmax, pagamentos parciais, split, multi-moeda, refund, disputas, taxas,
settlement, Messaging e fases posteriores seguem fora do escopo.

## Parecer

`APPROVED`. Os achados P05-R18 a P05-R21 estão resolvidos e não foi encontrado
novo achado bloqueante. Este parecer libera apenas o próximo checkpoint de
QA/Segurança mediante autorização humana. Não aprova produto, sandbox,
provider, PR, merge, release, deploy, alteração de `project/state.json` ou
fase posterior.
