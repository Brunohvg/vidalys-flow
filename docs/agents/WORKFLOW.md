# Workflow

O fluxo padrão de uma fase é:

1. confirmar `main` no `approved_head`;
2. criar `phase/<id>-<name>` a partir desse commit;
3. renderizar e executar o planejamento;
4. aguardar aprovação humana do plano;
5. renderizar e executar a implementação;
6. validar o handoff do implementador;
7. executar review independente;
8. executar QA e segurança;
9. entregar relatório consolidado;
10. aguardar aprovação humana da fase;
11. preparar PR e merge somente quando autorizados;
12. atualizar o estado oficial por ação de aprovação humana.

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
