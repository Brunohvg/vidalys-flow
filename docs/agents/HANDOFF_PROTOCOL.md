# Protocolo de handoff

O handoff é JSON versionado e contém somente fatos verificáveis. Campos
desconhecidos usam `null` ou `"not_recorded"`; SHAs, resultados e aprovações
nunca são inferidos.

Todo handoff deve conter:

- versão do schema, fase, nome, status, branch, base e HEAD;
- commits e escopo entregue;
- models e migrations afetados;
- testes, cobertura, scans e CI;
- isolamento organizacional e reutilização legada;
- itens adiados, riscos, bloqueadores e aprovação humana.

O implementador entrega status `candidate`. Review e QA acrescentam seus
relatórios sem converter o documento em aprovação. Um handoff histórico
`approved` precisa de aprovação humana já confirmada.

Em fases novas, `base_sha` é o `actual_base_sha`: o SHA exato de
`origin/main` resolvido antes da criação da branch. Ele não substitui
`dependency_head`, que permanece como evidência histórica da dependência.

Valide antes de entregar:

```bash
python scripts/agent_orchestrator.py validate-handoff project/handoffs/phase-02.json
```
