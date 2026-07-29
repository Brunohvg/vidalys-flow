# Estratégia de branches

`main` é a `baseline_branch`: contém todo o código de produto aprovado e pode
conter governança aprovada entre fases. `approved_phase_head` preserva a
evidência exata da última fase de produto, mas não precisa ser o HEAD de
`main`. O padrão futuro é:

```text
main
└── phase/<id>-<name>
```

Exemplos: `phase/03-orders`, `phase/04-fulfillment` e
`phase/05-payments`.

Cada fase nasce diretamente do SHA atual de `origin/main`, que deve conter
`approved_phase_head` como ancestral. Antes da criação, o agente executa:

```bash
git fetch origin main
git rev-parse origin/main
```

O SHA obtido é `actual_base_sha` no relatório e `base_sha` no handoff. A
dependência funcional é validada separadamente pelo `dependency_head` do
manifesto, que coincide com o `approved_sha` da fase dependida no roadmap.

Entre `approved_phase_head` e a baseline são aceitos apenas commits de
governança em `AGENTS.md`, `project/`, `docs/agents/`, `prompts/`, scripts e
testes de governança/scans e CI. Mudanças em apps, migrations, templates de
negócio ou dependências de produção exigem fase de produto própria.

Uma branch pertence a um único agente ativo por vez. Review e QA devem evitar
mutações; se uma correção for autorizada, ela volta ao implementador ou
ocorre em branch separada com handoff explícito.

PR, merge, release e atualização de `main` só acontecem após aprovação
humana. Branches históricas são preservadas; não há force-push, rebase
destrutivo, exclusão ou criação da fase seguinte sobre candidato não
aprovado.
