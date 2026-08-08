# Caminho até homologação e produção

O produto ainda não está autorizado para deploy. A sequência abaixo é o
caminho seguro e não pode ser interpretada como aprovação antecipada.

## Checkpoint atual

A Fase 03 — Orders permanece candidata. O checkpoint e as evidências correntes
estão em `project/handoffs/phase-03.json` e nos relatórios de Review em
`project/reviews/`. Antes da aprovação humana ainda são obrigatórios Review sem
bloqueadores e QA/Segurança com GO. Somente depois disso podem ser autorizados
PR/merge e o planejamento da fase seguinte.

## Sequência de produto

1. **Concluir Orders (Fase 03).** Corrigir achados, validar PostgreSQL,
   concorrência, segurança e handoff; obter aprovação humana.
2. **Fulfillment (Fase 04).** Planejar e implementar separação, entrega ou
   retirada sem misturar estados comerciais, financeiros e logísticos.
3. **Payments (Fase 05).** Modelar cobranças e links de pagamento de forma
   provider-agnostic; planejar Mercado Pago e Pagar.me como primeiros
   conectores e Appmax como conector posterior.
4. **Messaging (Fase 06).** Enviar comunicações transacionais somente a partir
   de eventos aprovados, com consentimento e rastreabilidade.
5. **Integrations (Fase 07).** Adicionar conectores externos com isolamento,
   retries, idempotência e circuitos de falha.
6. **Experiência completa (Fase 08).** Consolidar dashboards e jornadas de
   operação sem contornar policies dos domínios.
7. **Infraestrutura e homologação (Fase 09).** Provisionar ambiente vazio e
   exclusivo, configurar secrets por canal seguro, executar migrations,
   testes de aceitação, segurança, backup/restore e observabilidade.
8. **Go-live controlado (Fase 10).** Liberar produção somente após evidências
   de homologação, plano de rollback e aprovação humana. O encerramento
   operacional do sistema antigo não cria integração nem migração de dados.

## Gate repetido em cada fase

```text
planejamento
  → aprovação humana do plano
  → implementação em branch exclusiva
  → CI no SHA candidato
  → Review independente
  → QA e Segurança
  → relatório/handoff
  → aprovação humana da fase
  → PR/merge/release somente se autorizados
```

Falha em qualquer gate retorna à implementação. Uma aprovação técnica não
aprova produto, merge ou deploy.

## Homologação

Antes de produção será necessário comprovar, no mínimo:

- servidor ou ambiente computacional exclusivo da Vidalys Flow;
- PostgreSQL e Redis vazios e exclusivos, com backup e restore testados;
- DNS, TLS, e-mail e secrets próprios;
- migrations desde banco vazio e rollback técnico aprovado;
- testes unitários, integração, concorrência, cross-tenant e aceitação;
- testes de webhook e sandbox de cada provider financeiro;
- scans de secrets, independência, dependências e segurança;
- healthchecks, logs sanitizados, métricas, alertas e plano de incidente;
- rollback de aplicação e decisão humana de go-live.

## Situação da máquina independente

A arquitetura e o Compose demonstram que a Vidalys Flow foi desenhada para
runtime, banco e Redis próprios. O repositório, porém, não contém evidência de
uma máquina de produção já provisionada e aprovada. Portanto:

- **independência arquitetural:** comprovada;
- **máquina de produção independente:** pendente de comprovação/provisionamento
  na Fase 09;
- **deploy atual:** não autorizado e não realizado por este fluxo.
