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

O planejamento e a implementação da Fase 3 já foram concluídos. O checkpoint
atual é Review independente:

```bash
python scripts/agent_orchestrator.py render review 03
```

O candidato está em `phase/03-orders`, criado sobre o `actual_base_sha`
`75c335676c6ad258e5ff2832bb64a2a5a7d97fcc`. O handoff registra essa baseline
em `base_sha`; `dependency_head` continua sendo a evidência funcional da Fase
2 aprovada.

Os comandos dos checkpoints já concluídos permanecem disponíveis para
reprodução, mas não devem reiniciar planejamento ou implementação:

```bash
python scripts/agent_orchestrator.py render planning 03
python scripts/agent_orchestrator.py render implementation 03
```

Depois de Review completo e sem blockers, o próximo agente poderá renderizar
QA/Segurança:

```bash
python scripts/agent_orchestrator.py render qa-security 03
python scripts/agent_orchestrator.py validate-handoff project/handoffs/phase-03.json
```

`approval.md` é material exclusivo do aprovador humano. O orquestrador recusa
renderizá-lo para agentes. Prompts gerados não são versionados: redirecione a
saída para um diretório temporário fora do repositório quando necessário.
