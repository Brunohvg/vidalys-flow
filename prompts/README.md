# Prompts versionados

Os templates contêm somente a estrutura de cada checkpoint. O orquestrador
combina o template com `AGENTS.md` e o manifesto da fase, sem criar arquivos,
alterar estado ou executar a fase.

## Uso

Consulte e valide o estado:

```bash
python scripts/agent_orchestrator.py status
python scripts/agent_orchestrator.py validate-all
python scripts/agent_orchestrator.py validate-phase 03
```

Inicie apenas o planejamento da Fase 3:

```bash
python scripts/agent_orchestrator.py render planning 03
```

Após aprovação humana explícita do plano e atualização manual de
`plan_status` para `approved`:

```bash
python scripts/agent_orchestrator.py render implementation 03
```

Quando cada checkpoint anterior estiver registrado como concluído, use:

```bash
python scripts/agent_orchestrator.py render review 03
python scripts/agent_orchestrator.py render qa-security 03
python scripts/agent_orchestrator.py validate-handoff project/handoffs/phase-03.json
```

`approval.md` é material exclusivo do aprovador humano. O orquestrador recusa
renderizá-lo para agentes. Prompts gerados não são versionados: redirecione a
saída para um diretório temporário fora do repositório quando necessário.
