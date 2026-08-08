# Review independente 02 — Fase 03 Orders

- resultado: `CHANGES_REQUESTED`;
- candidato material: `f42dae3a52e78764ccda5a09cea559bd5dd83282`;
- transportador de handoff: `ece9b7853a5d412d3d176ca7793748f241840056`;
- CI material: run `31235650552`, sucesso, 177 testes e 86% de cobertura;
- QA/Segurança: bloqueado até remediação e novo Review independente.

## Achados

1. **Alto:** a confirmação bloqueava Order, mas não serializava Customer,
   Product e ProductVariant usados na validação e nos snapshots. Merge ou
   inativação concorrente podia invalidar a decisão depois da leitura.
2. **Médio:** OPERATOR não conseguia alterar quantidade, preço-base ou notas
   de uma linha que já possuía ajuste gerencial, mesmo preservando desconto e
   acréscimo.
3. **Baixo documental:** o handoff precisava esclarecer que 172 aprovados e 5
   ignorados pertenciam à execução Docker local, enquanto o CI com metadados
   Git executou os 177 testes.

Os achados da primeira revisão sobre PII, histórico, protocolo do handoff,
rollback e confirmação contra cancelamento foram considerados resolvidos. A
segunda revisão não aprova produto, fase, merge, PR ou release.
