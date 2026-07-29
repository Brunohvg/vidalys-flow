# Workflow

O fluxo padrão de uma fase é:

1. confirmar que `origin/main` contém `approved_phase_head` como ancestral;
2. confirmar que o intervalo contém somente produto ou governança aprovados;
3. resolver `git rev-parse origin/main` como `actual_base_sha`;
4. validar `dependency_head` contra a fase dependida no roadmap;
5. criar `phase/<id>-<name>` no `actual_base_sha`;
6. renderizar e executar o planejamento;
7. aguardar aprovação humana do plano;
8. renderizar e executar a implementação;
9. validar o handoff, cujo `base_sha` registra `actual_base_sha`;
10. executar review independente;
11. executar QA e segurança;
12. entregar relatório consolidado;
13. aguardar aprovação humana da fase;
14. preparar PR e merge somente quando autorizados;
15. atualizar o estado oficial por ação de aprovação humana.

## Exemplo: Fase 3

```bash
python scripts/agent_orchestrator.py status
python scripts/agent_orchestrator.py validate-phase 03
python scripts/agent_orchestrator.py render planning 03
```

Depois da aprovação humana do plano, o aprovador registra
`plan_status: approved` no manifesto. Só então:

```bash
python scripts/agent_orchestrator.py render implementation 03
python scripts/agent_orchestrator.py validate-handoff project/handoffs/phase-03.json
python scripts/agent_orchestrator.py render review 03
python scripts/agent_orchestrator.py render qa-security 03
```

Esses comandos preparam checkpoints; não iniciam Orders automaticamente. Cada
agente para após o relatório e aguarda o próximo aceite.
