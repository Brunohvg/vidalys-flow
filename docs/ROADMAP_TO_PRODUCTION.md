# Caminho até homologação e produção

O produto ainda não está autorizado para deploy. A sequência abaixo é o
caminho seguro e não pode ser interpretada como aprovação antecipada.

## Checkpoint atual

A Fase 03 — Orders foi aprovada e integrada. A Fase 04 — Fulfillment possui
implementação candidata em `phase/04-fulfillment`, sobre a baseline
`a98ceab40f9c40d19dd9c24b666846fb05e63b2d`. O Review 01 solicitou mudanças,
que foram implementadas e validadas localmente com PostgreSQL 17. O próximo
checkpoint é CI no SHA remediado, seguido de novo Review independente e
QA/Segurança. Não há autorização de merge ou deploy.

## Sequência de produto

1. **Orders (Fase 03, concluída).** Registro comercial, snapshots, valores e
   estados canônicos aprovados; sem cobrança ou logística.
2. **Fulfillment (Fase 04, candidata).** Revisar a implementação de lotes
   parciais, separação, entrega e retirada; executar QA/Segurança; produzir o
   relatório final; obter nova aprovação humana antes de PR/merge.
3. **Payments (Fase 05).** Modelar cobranças e links de pagamento de forma
   provider-agnostic; decidir o primeiro rollout entre Mercado Pago e Pagar.me
   conforme conta e sandbox; estabilizar ambos antes do Appmax.
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

## Ordens obrigatórias até teste e deploy

Cada fase de produto repete planejamento, aprovação do plano, implementação,
CI, Review independente, QA/Segurança, handoff, aprovação humana e merge. A
Fase 09 só começa depois das fases funcionais aprovadas e prepara ambiente
exclusivo, migrations desde banco vazio, backup/restore, observabilidade e
testes de aceitação. A Fase 10 executa o go-live apenas com rollback testado e
aprovação humana específica.

Payments não pode ser antecipado dentro de Fulfillment. Cada conector terá
credencial exclusiva da Vidalys Flow, checkout hospedado, webhook autenticado,
deduplicação, reconciliação, sandbox e rollout separado. Nada será reaproveitado
do Flowlog antigo.

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
