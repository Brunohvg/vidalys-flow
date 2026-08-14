# QA e Segurança — Fase 08 Dashboard and complete experience

- decisão técnica: `GO`;
- candidato material imutável: `f6b003971342eb43eac3a9653290dafdd45c3275`;
- Independent Review: `READY_FOR_QA_AND_SECURITY`, sem achados bloqueantes;
- carrier documental validado antes do registro de QA: `d50702bb942aa4c482dc95e336a9e4ecbad0e09c`;
- baseline (`actual_base_sha`): `005e11c1c7c14440562806fe0301f3a0ad4763b5`;
- dependency head aprovado: `cba7d6cbebbcf672bb313472d5e1d7e431e48df5`;
- Foundation CI material: run `31824394665`, número `179`, `success` no SHA material exato;
- Foundation CI do carrier pré-QA: run `31825973554`, número `184`, `success` no SHA `d50702bb942aa4c482dc95e336a9e4ecbad0e09c`;
- suíte material: 454 testes aprovados, 0 skipped;
- cobertura global: `86%` (mínimo 85%);
- PostgreSQL: `17.11`;
- blockers de QA/Security: nenhum.

## Decisão

`GO` técnico para a Fase 08 — Dashboard and complete experience.

Este GO não equivale a aprovação humana da fase e não autoriza PR, merge, provider real, sandbox, callback público, credenciais, release, deploy ou Fase 09.

## P08-QA-SEC-001

Status: `RESOLVED / PASS`.

O `Order Workspace` primeiro obtém o `Order` exigindo `Order.organization = active Organization`, `Order.customer.organization = active Organization` e o `id` solicitado. Para o pagamento, o selector exige simultaneamente `PaymentIntent.organization = active Organization`, `PaymentIntent.order.organization = active Organization` e `PaymentIntent.order = scoped Order`. Para fulfillment, exige simultaneamente `Fulfillment.organization = active Organization`, `Fulfillment.order.organization = active Organization` e `Fulfillment.order = scoped Order`.

O teste adversarial `test_order_workspace_rejects_cross_organization_related_records` cria `PaymentIntent` e `Fulfillment` de outra Organization ainda apontando para o Order da Organization ativa e confirma que o workspace retorna `payment is None` e nenhum fulfillment. O finding não depende de consistência relacional implícita e permanece corrigido.

## P08-QA-SEC-002

Status: `RESOLVED / PASS`.

Todos os relacionamentos atualmente atravessados ou renderizados pelo Dashboard são validados nos próprios selectors com Organization explícita tanto no objeto raiz quanto na relação relevante:

- `Order -> Customer`;
- `PaymentIntent -> Order`;
- `Fulfillment -> Order`;
- `Message -> Customer`;
- `Message -> Channel`;
- `IntegrationDelivery -> Connection`;
- `IntegrationDelivery -> Endpoint`.

Os testes adversariais confirmam fail-closed para `PaymentIntent Org A -> Order Org B`, `Fulfillment Org A -> Order Org B`, `Order Org A -> Customer Org B`, `Message Org A -> Customer/Channel Org B` e `IntegrationDelivery Org A -> Connection/Endpoint Org B`. Esses registros ficam fora dos selectors/contagens afetados e não chegam aos templates, portanto não expõem identificador, número, display name ou campo relacionado do tenant estrangeiro.

## Autenticação, autorização e Organization

As duas views do Dashboard continuam protegidas por `@login_required` e `@require_GET`. A Organization ativa é obtida por `active_organization_for_user(user=request.user, session=request.session)` e não existe Organization arbitrária recebida por request.

O selector de Organizations considera somente Membership ativa e Organization ativa. Um `active_organization_id` de sessão que não pertença às Memberships ativas do usuário é rejeitado e removido da sessão. Com múltiplas Memberships e nenhuma seleção válida o selector retorna `None, None`, e o Dashboard redireciona para seleção de Organization. O comportamento é fail-closed.

## Read-only, persistência e privacidade

Dashboard permanece uma camada de leitura. As views aceitam somente GET e os testes exigem HTTP 405 para POST. `apps.dashboard` não possui model de persistência nem migrations, e o teste de app confirma zero models.

Os templates renderizam somente identificadores operacionais, display/snapshot names mínimos, status e valores canônicos necessários à operação. Não renderizam raw provider payload, webhook secret, credencial, token, contato privado completo ou metadata arbitrária de provider/integration.

O Order Workspace continua somente compondo `Order`, `Customer`, `PaymentIntent`, `Fulfillment` e mensagens canônicas; não cria estado ou lifecycle paralelo.

## KPIs, attention queues e desempenho

KPIs e filas continuam derivados dos estados canônicos já aprovados. O segundo rework apenas adicionou predicates de tenant e não alterou classificação de estados.

As listas permanecem limitadas por `DASHBOARD_LIMIT`. Relações renderizadas usam `select_related` onde aplicável. O teste `test_recent_orders_keeps_customer_reads_in_one_query` mantém a regressão de N+1 do bounded recent-orders list.

## PostgreSQL, migrations e regressão

Foundation CI #179 executou no SHA material exato `f6b003971342eb43eac3a9653290dafdd45c3275`, em PostgreSQL 17.11. O checkout confirmou o SHA exato antes dos gates.

A suíte coletou 454 testes e terminou com 454 passed, 0 skipped e cobertura global de 86%. `makemigrations --check --dry-run` retornou `No changes detected`. A base vazia recebeu todas as migrations e os gates de rollback/reapply de Fulfillment, Payments, Messaging e Integrations passaram.

Secret scan, independence scan, Ruff, Django check, governance/baseline, Docker build, Compose validation e topologia Celery passaram. O gate Celery confirmou as filas `default` e `integrations`.

## Independência, efeitos externos e escopo

O delta material do segundo rework é restrito aos selectors e testes do Dashboard. O independence scan não encontrou símbolos proibidos e o secret scan não encontrou assinatura de secret real.

Não foi introduzido ou executado Flowlog runtime/data/code/infrastructure reuse, provider real, sandbox, credencial, callback público, deploy, release, Coolify ou implementação da Fase 09.

## Findings não bloqueantes

1. GitHub Actions informa depreciação do Node.js 20 para `actions/checkout@v4` e `astral-sh/setup-uv@v5`; o runner os executou sob Node.js 24 e os dois CIs verificados concluíram com sucesso. É manutenção de CI, não blocker da Fase 08.

## Riscos residuais

1. O Dashboard é um read model síncrono; maior volume futuro pode exigir projection/cache, fora do escopo da Fase 08.
2. Toda nova relação adicionada ao Dashboard deve continuar validando Organization no objeto raiz e em cada relação atravessada/renderizada, acompanhada de teste adversarial cross-tenant.
3. Attention queues devem continuar apenas refletindo estados canônicos, sem adquirir lifecycle ou regras de negócio próprias.

## Veredito

`GO`.

Não há finding bloqueante de QA/Security para o candidato material `f6b003971342eb43eac3a9653290dafdd45c3275`.

`P08-QA-SEC-001`: `RESOLVED / PASS`.

`P08-QA-SEC-002`: `RESOLVED / PASS`.

Próximo checkpoint permitido pela governança é somente a aprovação humana final da Fase 08. Até essa decisão, `human_approval_status` permanece `pending` e PR, merge, release, deploy, providers reais, sandbox, callbacks públicos, credenciais e Fase 09 continuam não autorizados.
