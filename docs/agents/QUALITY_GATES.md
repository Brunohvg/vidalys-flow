# Quality gates

Os gates normativos estão em `project/constraints.json`; os scanners
executáveis complementares são `scripts/check_secrets.py` e
`scripts/check_independence.py`.

## Gates mínimos

- escopo permitido e proibido conferido no manifesto;
- `approved_phase_head` é ancestral da baseline e do candidato;
- commits entre a fase aprovada e a baseline alteram somente caminhos de
  governança permitidos;
- `dependency_head` coincide com a fase aprovada no roadmap;
- `base_sha` do handoff registra o `actual_base_sha` usado;
- organização explícita e teste cross-tenant para toda entidade operacional;
- migrations novas aplicadas e revertidas tecnicamente em PostgreSQL;
- testes de sucesso, erro, autorização, isolamento, idempotência e
  concorrência quando aplicáveis;
- cobertura total mínima de 85%;
- Ruff, Django check e migration consistency aprovados;
- secret e independence scans aprovados;
- Docker build e Compose config aprovados;
- handoff estruturado e validado;
- review independente sem achados bloqueantes;
- QA e segurança com GO técnico;
- GitHub Actions no HEAD candidato com sucesso;
- aprovação humana explícita antes de PR, merge ou release.

Um gate técnico aprovado não modifica `project/state.json` e não autoriza a
próxima fase.
