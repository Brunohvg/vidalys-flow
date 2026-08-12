# QA e Segurança 02 — Fase 05 Payments

- decisão técnica: `GO`;
- checkpoint: QA/Segurança independente final, focado na remediação do
  runtime Celery e em regressão de segurança do delta;
- branch: `phase/05-payments`;
- candidato material imutável:
  `09fe3615008fe1621e46ecee74d6a2b58667377b`;
- carrier de Review 05 observado:
  `03868a75a3753b165ca2584f53caf6c31a6708a8`;
- baseline (`actual_base_sha`):
  `4fd3a9259e9e2f31acdab44f13499eade79ab59e`;
- dependência aprovada:
  `888685886d7a17c6eeb008674be86656e4f6fa40`;
- Review 05: `APPROVED`, sem blocker;
- achados bloqueantes: nenhum.

## Decisão

`GO`. P05-Q01 e P05-Q02 foram corrigidos e revalidados no código, no gate
executável e em um runtime reconstruído. As três tasks de Payments foram
descobertas; Beat e os workers ficaram saudáveis; cada worker consumiu somente
sua fila, com exchange direto e routing keys distintos. Não surgiu evidência
nova que reabra o domínio financeiro aprovado.

P05-Q03 permanece resolvido. A frase temporal P05-R22 foi alinhada neste
fechamento exclusivamente documental, sem alteração de código de domínio.

Este GO é apenas técnico. Não aprova produto ou fase e não autoriza mudança em
`project/state.json`, provider, sandbox, webhook público, PR, merge, release,
deploy ou fase posterior.

## Git, ancestralidade e fronteira

- `dependency_head` é ancestral da baseline;
- a baseline é ancestral do candidato material;
- o histórico entre baseline e candidato é linear, sem merge commit;
- o delta material da remediação está limitado a configuração Celery,
  Compose, gate operacional, teste e documentação;
- `origin/main` permaneceu em
  `4fd3a9259e9e2f31acdab44f13499eade79ab59e`;
- este checkpoint não alterou código de domínio.

## CI nos SHAs exatos

- candidato material: run `31585187061`, `success`, SHA
  `09fe3615008fe1621e46ecee74d6a2b58667377b`;
- carrier do candidato: run `31585362155`, `success`, SHA
  `570dd8c55c69465ca69dc90fbebfa2ed3c079e81`;
- carrier do Review 05: run `31586780875`, `success`, SHA
  `03868a75a3753b165ca2584f53caf6c31a6708a8`.

Os três runs concluíram no SHA informado. O CI material executou governança,
scanners, Ruff, Django, migrations, testes PostgreSQL, cobertura, build Docker,
validação dos Compose e o gate de topologia Celery.

## PostgreSQL, testes e qualidade

- `validate-all` e baseline/governança: aprovados;
- scanners de secrets e independência: aprovados;
- Ruff, Django check, migration consistency e `git diff --check`: aprovados;
- 277 testes em PostgreSQL: aprovados, nenhum skip;
- 70 testes diretos de Payments: aprovados;
- cobertura exata independente: 85,24744994333207%, acima do gate de 85%;
- Docker build e os dois arquivos Compose: aprovados;
- PostgreSQL 17.10 efêmero vazio: todas as migrations aplicadas;
- rollback de Payments até zero e reaplicação até
  `0004_paymentattempt_cancellation_correlation`: aprovados;
- repetição na imagem de teste: 272 aprovados e cinco skips esperados dos
  testes de baseline, pois a imagem deliberadamente não contém `.git`.

O aviso de teardown da base de teste causado por conexões concorrentes ainda
apareceu na execução em container, mas o processo terminou com código zero e a
execução local com contexto Git completo teve 277 aprovações e zero skips.
Trata-se de risco operacional conhecido e não bloqueante, não de falha da
remediação.

## Runtime Celery reconstruído

O runtime foi reconstruído a partir da branch candidata, usando PostgreSQL e
Redis locais saudáveis. O serviço `migrate` terminou com código zero. Beat,
`worker-default` e `worker-integrations` alcançaram healthcheck saudável.

Ambos os workers registraram as seis tasks agendadas ou roteadas, incluindo:

- `apps.payments.tasks.consume_order_cancellations`;
- `apps.payments.tasks.dispatch_checkout_requests`;
- `apps.payments.tasks.dispatch_checkout_cancellations`.

A topologia real confirmou:

- `worker-default`: exclusivamente fila `default`, exchange `vidalys` do tipo
  `direct`, routing key `default`;
- `worker-integrations`: exclusivamente fila `integrations`, exchange
  `vidalys` do tipo `direct`, routing key `integrations`;
- nenhuma fila apareceu simultaneamente nos dois workers;
- Beat publicou consumers internos para `default` e dispatch/cancelamento de
  checkout para `integrations`;
- as tasks executadas retornaram sem provider I/O e sem erro.

O script `scripts/check_celery_runtime.py` passou no contrato real. Três
cenários negativos independentes confirmaram falha fechada e exit code 1 para:

- task agendada/roteada ausente do registro;
- fila roteada sem consumer no Compose;
- duas filas roteadas compartilhando o mesmo par exchange/routing key.

Os containers efêmeros de teste, migration, Beat e workers foram removidos ao
final. PostgreSQL e Redis locais preexistentes permaneceram intactos e
saudáveis.

## Segurança e regressão do delta

O delta não altera models, migrations, services, selectors, policies,
callbacks, adapters ou interfaces de Payments. A suíte direta preservou
Organization explícita, manager tier, masking de OPERATOR, idempotência,
`expected_version`, locks, tentativa única, leases, correlação exata de
cancelamento, evidência sanitizada, callbacks autenticados e constraints de
banco.

Mercado Pago permaneceu sem credencial e sem chamada. O callback Pagar.me
continuou bloqueado por aplicação e PostgreSQL. Os adapters reais mantiveram
efeitos externos desabilitados, e os testes bloquearam resolução DNS dos
hosts conhecidos. Appmax e Flowlog permaneceram ausentes; não houve rede de
provider, sandbox, registro de webhook, cobrança, reutilização de runtime ou
infraestrutura antiga.

## Riscos residuais não bloqueantes

- cobertura global de 85,24744994333207% permanece acima do mínimo por margem
  estreita, embora os caminhos financeiros e operacionais tenham testes
  comportamentais diretos;
- o rate limiter depende de Redis e falha fechado; alertas e capacidade devem
  ser validados em homologação;
- o callback Pagar.me deve continuar bloqueado até contrato de autenticidade e
  Security Review futuros;
- credenciais, fixtures de sandbox, observabilidade, carga, registro público
  de webhook e ativação de provider ainda exigem checkpoints próprios;
- o aviso de teardown de conexões PostgreSQL concorrentes deve continuar
  monitorado, apesar de não afetar o resultado das suítes.

## Próximo checkpoint

O candidato possui Review independente `APPROVED` e QA/Security `GO`. O
próximo passo é exclusivamente a decisão humana final sobre a Fase 05. Até
essa decisão, `human_approval_status` permanece `pending`, a fase continua
`candidate`, `project/state.json` não muda e PR, merge, release, deploy,
provider e fase seguinte permanecem proibidos.
