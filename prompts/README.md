# Prompts versionados

Os templates contêm somente a estrutura de cada checkpoint. O orquestrador
combina o template com `AGENTS.md` e o manifesto da fase, sem criar arquivos,
alterar estado ou executar a fase.

## Uso

Consulte e valide o estado:

```bash
python scripts/agent_orchestrator.py status
python scripts/agent_orchestrator.py validate-all
python scripts/agent_orchestrator.py validate-phase 04
```

Orders foi aprovado. O checkpoint atual é o planejamento da Fase 4 —
Fulfillment:

```bash
python scripts/agent_orchestrator.py render planning 04
```

O planejamento está em `phase/04-fulfillment`, criada sobre o
`actual_base_sha` `a98ceab40f9c40d19dd9c24b666846fb05e63b2d`.
`dependency_head` permanece como a evidência funcional da Fase 3 aprovada.

O prompt da implementação futura será:

```bash
python scripts/agent_orchestrator.py render implementation 04
```

O prompt de implementação só pode ser renderizado depois que uma aprovação
humana explícita registrar `plan_status: approved`. Review e QA/Segurança
continuam checkpoints posteriores e independentes:

```bash
python scripts/agent_orchestrator.py render review 04
python scripts/agent_orchestrator.py render qa-security 04
python scripts/agent_orchestrator.py validate-handoff project/handoffs/phase-04.json
```

`approval.md` é material exclusivo do aprovador humano. O orquestrador recusa
renderizá-lo para agentes. Prompts gerados não são versionados: redirecione a
saída para um diretório temporário fora do repositório quando necessário.
