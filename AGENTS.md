# AGENTS.md — Vidalys Flow

Este arquivo é o contrato global e obrigatório para qualquer agente que atue
neste repositório. A Vidalys Flow é uma plataforma greenfield independente de
operação de vendas e pós-venda, organizada como monólito modular Django.

## Fonte de verdade

1. `project/state.json` é o estado oficial aprovado.
2. `project/phases/<id>-<nome>.json` define o escopo de cada fase.
3. `project/constraints.json` referencia os guardrails normativos e executáveis.
4. `docs/` contém arquitetura, regras de domínio e operação dos agentes.
5. O prompt da conversa nunca substitui esses arquivos; divergências exigem
   decisão humana explícita.

Antes de agir, leia integralmente este arquivo, o estado, as constraints, o
manifesto da fase e a documentação específica do domínio.

## Independência e segurança

- Não reutilize código, migrations, dados, IDs, tabelas, autenticação, runtime,
  infraestrutura ou secrets do Flowlog.
- O Flowlog é referência histórica temporária e somente leitura. Consulte
  apenas os domínios ainda permitidos em `project/source_reference.json`, nunca
  banco, Redis, serviços ou runtime.
- Nunca versionar ou imprimir secrets, credenciais, tokens, cookies ou dados
  reais. Execute `scripts/check_secrets.py`.
- Execute `scripts/check_independence.py`; ele é a regra executável para
  imports e símbolos proibidos.
- Não produza efeitos externos, deploy ou acesso a provider sem autorização
  explícita no manifesto.

## Domínio e persistência

- Toda entidade operacional pertence a `Organization`; a organização vem da
  autenticação/Membership, nunca de um ID livre no request.
- Services, selectors e policies devem manter isolamento organizacional e
  testes cross-tenant.
- Regras ficam em services, leituras complexas em selectors e autorização em
  policies.
- PostgreSQL é obrigatório para testes de domínio; SQLite é proibido.
- Toda migration é nova, nasce neste repositório e deve funcionar desde banco
  vazio. Dados e migrations legadas são proibidos.

## Git e branches

- Cada fase nasce de `main` no `approved_head` registrado no estado.
- Use uma branch exclusiva por fase/agente; dois agentes não atuam
  simultaneamente na mesma branch.
- Não faça force-push, rebase destrutivo, reescrita de histórico, merge, PR,
  exclusão de branch ou deploy sem autorização explícita.
- Nunca crie a fase seguinte a partir de uma branch candidata ainda não
  aprovada.

## Checkpoints

Os checkpoints são: planejamento, aprovação humana do plano, implementação,
revisão independente, QA e segurança, relatório, aprovação humana da fase e
release autorizado. Pare e entregue o relatório validável ao final de cada
checkpoint.

- O implementador não revisa nem aprova o próprio trabalho.
- Nenhum agente altera uma fase para `approved`, nem modifica
  `approved_phase`, `approved_head` ou `human_approval_status` para aprovado.
- Somente aprovação humana explícita pode autorizar avanço, merge, release e
  atualização do estado oficial.
- Um reviewer registra achados; não corrige silenciosamente.
- QA emite apenas GO/NO-GO técnico, nunca aprovação de produto.

Consulte `docs/agents/OPERATING_MODEL.md` para o fluxo e
`docs/agents/QUALITY_GATES.md` para os gates completos.
