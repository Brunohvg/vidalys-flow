# Review independente 01 — Fase 03 Orders

- resultado: `CHANGES_REQUESTED`;
- alvo observado: `cf85b8fff6214d2f01e9bd3fd74d54960885ccc2`;
- CI observado: run `31235217510`, sucesso, 174 testes e 86% de cobertura;
- QA/Segurança: bloqueado até remediação e novo Review independente.

## Achados bloqueadores

1. Snapshots de Product/ProductVariant eram capturados somente na inclusão do
   item e podiam ficar obsoletos antes da confirmação.
2. A exibição sem máscara verificava apenas o papel informado, sem revalidar
   organização, usuário e atividade da Membership.
3. OrderStatusHistory impedia delete por instância, mas ainda permitia
   reescrita por save/update.
4. A semântica do SHA material e do commit que transporta o handoff precisava
   ser formalizada para evitar evidência autorreferente.

## Achados adicionais

1. O rollback técnico da migration não possuía execução reproduzível no CI.
2. Faltava teste direto da concorrência entre confirmação e cancelamento.

Este relatório registra achados; não aprova produto, implementação, merge ou
release. A remediação deve receber novo CI e novo Review independente.
