# Checkpoint: {{CHECKPOINT}}

Papel: {{ROLE}}
Fase: {{PHASE_ID}} — {{PHASE_NAME}}
Dependência aprovada: `{{DEPENDENCY_HEAD}}`
Referência de baseline: `{{BASE_REF}}`
Branch: `{{BRANCH}}`

## Escopo permitido

{{ALLOWED_SCOPE}}

## Escopo proibido

{{FORBIDDEN_SCOPE}}

Antes de criar ou usar a branch, resolva `origin/{{BASE_REF}}` e registre o
SHA como `actual_base_sha`. Implemente somente o plano aprovado, preserve o
estado oficial e produza um candidato e um handoff cujo `base_sha` seja esse
SHA real.

## Checks

{{CHECKS}}

## Relatório

{{REPORT_FORMAT}}

Não aprove o próprio trabalho. Pare após o handoff e aguarde review.
