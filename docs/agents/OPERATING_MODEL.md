# Modelo operacional dos agentes

O repositório é a fonte portátil de verdade para planejamento, execução,
revisão e aprovação. Cada sessão começa pela leitura de `AGENTS.md`,
`project/state.json`, `project/constraints.json` e do manifesto da fase.

Uma fase é um candidato imutavelmente baseado no último SHA aprovado. Seus
cinco estados de checkpoint são independentes: plano, implementação, revisão,
QA/segurança e aprovação humana. Nenhum resultado técnico equivale a
aprovação do produto.

## Separação de responsabilidade

- planejamento é somente leitura;
- implementação produz código e handoff, mas não aprovação;
- review registra achados sem correção silenciosa;
- QA valida evidências e emite GO/NO-GO técnico;
- somente o aprovador humano avança o estado oficial;
- release ocorre apenas depois da aprovação.

Ao concluir um checkpoint, o agente valida seu relatório, para e aguarda a
decisão humana. O agente seguinte trabalha em branch própria ou assume a
branch candidata somente quando não houver outro agente ativo nela.

O orquestrador apenas lê e valida artefatos. Ele não edita o estado, executa
Git, chama GitHub, consulta o Flowlog ou acessa secrets.
