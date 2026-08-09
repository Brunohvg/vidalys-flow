# Incidente de governança — recuperação da Fase 04

Data da constatação e ratificação: 8 de agosto de 2026.

## Resumo

A implementação material de Fulfillment em
`70364bc7c8a381dc958b2c7e2976f6d28d015023` recebeu CI verde, Review 02
`APPROVED` e QA/Segurança `GO`. Apesar disso, a PR #3 foi mesclada antes de
existir no repositório uma evidência separada e inequívoca da aprovação humana
final exigida pelos checkpoints.

O merge `323861ef62db547a3947f63018a16b908cbc0f55` fez o CI da `main` falhar no
gate de baseline porque o estado oficial ainda apontava para a Fase 3. A PR #5
tentou regularizar o estado em `a34cd4754b766a063ce081dff85861e3ebf2bcca`,
mas foi mesclada com o CI vermelho e deixou três testes do orquestrador e
diversos documentos operacionais desatualizados.

Também foi criada a implementação paralela
`origin/work/phase-04-fulfillment-001`, associada à PR #4 fechada como
duplicada. Ela não faz parte do produto aprovado e não deve ser usada como
base, mesclada ou copiada para fases posteriores.

## Decisão humana de recuperação

Após receber o diagnóstico completo, Bruno Vidal autorizou explicitamente na
conversa do projeto, em 8 de agosto de 2026, a correção integral segundo o
caminho recomendado e a continuação do desenvolvimento. Essa decisão:

- ratifica o resultado material revisado da Fase 4;
- autoriza uma correção progressiva, sem reset, force-push ou reescrita;
- não declara que a aprovação existia antes do merge;
- mantém o incidente e os CIs vermelhos anteriores como evidência histórica;
- exige a recuperação da suíte integral e da documentação antes do próximo
  checkpoint de Payments.

## Contenção e recuperação

- nenhuma mudança da branch paralela será incorporada;
- Payments não receberá código antes de plano técnico próprio e aprovação
  humana explícita;
- testes de governança passarão a refletir a Fase 4 ratificada e continuarão
  comprovando que um agente não pode aprovar uma fase futura;
- README, estado operacional, fluxo, arquitetura, segurança, clonagem e
  roadmap serão sincronizados;
- a correção só estará concluída com todos os gates e o CI do novo HEAD verdes.

## Evidências preservadas

- candidato material: `70364bc7c8a381dc958b2c7e2976f6d28d015023`;
- carrier de Review/QA: `7b2e92d939e9fd39b3baec1c12b900297a0d6548`;
- CI verde do candidato: run `31259856105`;
- merge da implementação: PR #3, commit
  `323861ef62db547a3947f63018a16b908cbc0f55`;
- CI vermelho pós-merge: run `31263813237`;
- regularização incompleta: PR #5, commit
  `a34cd4754b766a063ce081dff85861e3ebf2bcca`;
- CI vermelho da regularização: runs `31265206696` e `31265512810`;
- implementação duplicada não incorporada: PR #4 e branch
  `origin/work/phase-04-fulfillment-001`.
