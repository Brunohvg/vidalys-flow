# QA e Segurança — Fase 04 Fulfillment

- decisão técnica: `GO`;
- candidato material: `70364bc7c8a381dc958b2c7e2976f6d28d015023`;
- CI: run `31259856105`, sucesso no SHA exato;
- PostgreSQL 17 vazio, rollback e reaplicação: aprovados;
- testes no CI: 208 aprovados, nenhum skip, cobertura total de 86%;
- repetição local isolada: 203 aprovados e 5 testes de governança ignorados
  porque a imagem Docker deliberadamente não contém `.git`;
- secrets, independência, governança, Ruff, Django, migrations, Docker e
  Compose: aprovados;
- achados bloqueantes: nenhum.

## Evidências validadas

- O `approved_phase_head` é ancestral da baseline, e a baseline é ancestral do
  candidato. O `dependency_head` e o `base_sha` coincidem com os registros
  canônicos da fase.
- O GitHub Actions executou no SHA exato do candidato e aprovou instalação
  locked, governança, scans, lint, checks Django, migrations, suíte, cobertura,
  build Docker e validação dos dois Compose.
- O Compose de teste criou um PostgreSQL 17.10 efêmero vazio, aplicou todas as
  migrations, reverteu Fulfillment até zero, reaplicou suas duas migrations e
  concluiu a suíte sem falha. A cobertura total permaneceu em 86%, acima do
  mínimo de 85%.
- Os quatro testes PostgreSQL de concorrência cobrem criação parcial,
  substituição contra criação, transição contra cancelamento manual e evento
  de cancelamento do Order contra avanço do lote. A ordem de locks
  `Order -> Fulfillment` serializou os comandos sem deadlock e preservou
  quantidades, versão e estados válidos.
- Services, selectors, policies e consumidor de evento recebem ou revalidam a
  Organization. Há evidência direta para leitura, pedido, item, unidade e
  evento cross-tenant, derivação por Membership ativa e masking de OPERATOR.
- Idempotência, conflito de payload, `expected_version`, retry do evento,
  evento fora de ordem e preservação de lote concluído foram exercitados sem
  duplicar recibos, histórico, audit ou outbox.
- AuditEvent, OutboxEvent, command receipts, logs e exceptions foram
  verificados contra endereço, documento, contato e motivo livre. Esses dados
  não aparecem nas evidências operacionais; o motivo permanece somente no
  campo canônico autorizado do Fulfillment.
- PostgreSQL e Redis estão saudáveis no runtime local. O worker confirmou a
  task `apps.fulfillment.tasks.consume_order_cancellations` registrada na fila
  `default`, e o Beat confirmou o agendamento periódico.
- Não foram encontrados providers, chamadas externas, Payments, inventory,
  Messaging, reutilização de Flowlog, migrations legadas ou efeitos externos.

## Riscos residuais não bloqueantes

- O OPERATOR vê o destino de entrega mascarado conforme o contrato aprovado;
  a adequação ao trabalho operacional deve ser confirmada em homologação.
- O consumidor de cancelamento compartilha a fila Celery `default`; backlog,
  retry e latência precisam de observabilidade na homologação.
- O CI registrou um aviso de teardown porque duas conexões PostgreSQL dos
  testes concorrentes ainda estavam visíveis ao excluir a base. Os 208 testes
  passaram, as threads fecham conexões explicitamente e a repetição isolada
  terminou com exit code zero, portanto o aviso não bloqueia este gate, mas a
  higiene de conexões deve continuar monitorada.
- O Redis local avisou que `vm.overcommit_memory` está desabilitado no host
  WSL. Isso não afetou os testes nem a saúde do runtime, mas deve ser ajustado
  antes de homologação com carga.

Este `GO` é exclusivamente técnico. Não aprova produto ou fase, não autoriza
PR, merge, release, deploy, alteração de `project/state.json` nem início da
Fase 05. O próximo checkpoint é o relatório final para decisão humana
explícita.
