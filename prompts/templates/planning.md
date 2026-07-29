# Checkpoint: {{CHECKPOINT}}

Papel: {{ROLE}}
Fase: {{PHASE_ID}} — {{PHASE_NAME}}
Dependência aprovada: `{{DEPENDENCY_HEAD}}`
Referência de baseline: `{{BASE_REF}}`
Branch proposta: `{{BRANCH}}`

## Escopo permitido

{{ALLOWED_SCOPE}}

## Escopo proibido

{{FORBIDDEN_SCOPE}}

## Trabalho e checks

Audite somente as referências autorizadas, declare regras, riscos,
dependências, estados e decisões que exigem aprovação. Confirme que o executor
deverá registrar `actual_base_sha` antes de criar a branch. Não modifique
código de domínio.

{{CHECKS}}

## Relatório

{{REPORT_FORMAT}}

Pare após entregar o plano e aguarde aprovação humana explícita.
