# Fluxo funcional da Vidalys Flow

Este documento separa o que já existe do que pertence ao produto-alvo. A
fonte oficial de estado continua sendo `project/state.json` e os manifestos de
fase.

## Princípio central

A Vidalys Flow é um produto greenfield. Ela não sincroniza, consulta ou
compartilha banco, Redis, arquivos, usuários, IDs, autenticação, secrets,
workers, webhooks, runtime, servidor ou deploy com o Flowlog antigo. A
referência histórica permitida pelo processo serve somente para compreender
ideias de produto ainda não reconstruídas e nunca cria uma ligação técnica.

## Fluxo aprovado hoje

```text
login
  → seleção de Organization autorizada por Membership ativa
  → Customers e endereços/contatos
  → Products e variantes
  → Order draft e itens
  → validação, snapshots e confirmação
  ├─→ Fulfillment parcial de entrega ou retirada
  └─→ PaymentIntent integral em BRL
       → tentativa única de checkout hospedado
       → callback autenticado ou reconciliação
       → estado financeiro canônico
  → histórico + AuditEvent + OutboxEvent internos
```

1. O usuário autentica com identidade nativa da Vidalys Flow.
2. Seleciona uma Organization da qual possui Membership ativa.
3. Toda leitura e escrita revalida essa Organization; IDs isolados nunca
   autorizam acesso.
4. Customers mantém identidade, documento normalizado, contatos, endereços e
   merge explícito.
5. Products mantém catálogo, variantes, SKU e identificadores por
   Organization.
6. Orders cria rascunhos numerados como `PED-000001`, aceita itens de catálogo
   ou livres e calcula valores no servidor.
7. Na confirmação, o pedido bloqueia e relê suas fontes comerciais, valida
   Customer/Product/Variant e congela os snapshots aprovados.
8. Mudanças relevantes geram histórico de estado, auditoria sanitizada e
   eventos internos na mesma transação.

Orders não cobra, separa, entrega, envia mensagens, emite documento fiscal ou
chama providers. Fulfillment executa separação, entrega e retirada em módulo
próprio, sem alterar o estado comercial do pedido.

Payments é um módulo aprovado e separado. Apenas manager tier cria intents e
solicita links. OPERATOR consulta estado e copia um link já ativo, com
evidências externas e dados pessoais ocultos. Nenhuma mensagem é enviada
automaticamente no produto aprovado atual.

```text
Order confirmed + total BRL positivo
  → PaymentIntent pending
  → PaymentAttempt requested
  → outbox + worker com revalidação e lease de 90 s (adapter real bloqueado)
  → active / awaiting_payment
  → processing | paid | failed→pending | cancelled | expired | requires_attention
```

Somente um attempt pode estar solicitado, ativo ou processando. O provider não
dita o modelo canônico. Divergência de valor/moeda, evento regressivo ou
cancelamento de Order com cobrança aberta/paga gera `requires_attention`, sem
reembolso automático e sem mudar Order ou Fulfillment.
Dispatch usa backoff persistente e reutiliza a mesma tentativa e chave após
timeout. Mudança de Order/conta durante I/O preserva o link externo e sinaliza
atenção. Cancelamento de link externo passa por outbox e confirmação
autoritativa; só depois há reabertura e escolha humana de outro provider.
Callbacks deduplicam somente identificadores autenticados e não resolvem
`requires_attention` sem evidência verificada.

## Fluxo aprovado da Fase 4

```text
Order confirmed
  → lote Fulfillment draft
  → preparing
  → ready
  ├─ delivery → in_transit → completed
  └─ pickup ───────────────→ completed
```

Vários lotes podem atender parcialmente o mesmo pedido sem superar a
quantidade confirmada. O progresso é logístico e não cria `completed` em
Order. Cancelamento comercial é coordenado por evento interno idempotente;
estoque, pagamentos, transportadoras, mensagens e integrações não participam.

## Papéis

- OWNER, ADMIN, MANAGER e OPERATOR consultam pedidos, criam/editam drafts,
  informam preço-base e confirmam;
- OWNER, ADMIN e MANAGER aplicam desconto/acréscimo, cancelam e visualizam PII
  sem máscara;
- OPERATOR recebe documento, contato e endereço mascarados;
- a permissão é sempre organizacional e nunca global no User.

## Plano da Fase 6 — ainda não aprovado

```text
evento aprovado ou comando manual allowlisted
  → template transacional versionado
  → Customer + ContactPoint + permissão revalidados
  → Message + tentativa idempotente
  → WhatsApp Cloud API ou Amazon SES (efeito externo desligado)
  → callback autenticado
  → sent / delivered / failed / requires_attention
```

O plano de Messaging não aceita texto livre, marketing ou contato sem
permissão vigente. Regras automáticas começam desabilitadas por Organization.
Antes de enviar checkout, o worker relê a tentativa exata de Payments; links
expirados, cancelados, substituídos ou em atenção não são enviados. Essa seção
descreve uma proposta e não autoriza código nem provider.

## Fluxo-alvo do produto completo

```text
Customer + Product
        ↓
      Order
        ↓
   Fulfillment
        ↓
Payment link ──→ provider externo ──→ webhook verificado
        ↓                              ↓
 estado financeiro canônico ← reconciliação idempotente
        ↓
 Messaging / Integrations / Dashboard
        ↓
 homologação isolada → aprovação humana → produção isolada
```

O núcleo de Payments está aprovado, mas nenhum provider ou deploy está ativo.
Messaging está em planejamento; Integrations, Dashboard e ambientes externos
continuam futuros. Cada seta externa só é liberada por contrato, testes,
Review, QA/Segurança e aprovação humana.

## Regras transversais

- PostgreSQL é a fonte transacional; Redis é exclusivo da Vidalys Flow;
- toda entidade operacional pertence a uma Organization;
- services executam regras, selectors fazem leituras e policies autorizam;
- comandos críticos são idempotentes e concorrência é explicitamente testada;
- dados pessoais não entram em logs, AuditEvent ou OutboxEvent;
- integrações externas ficam desligadas por padrão e exigem autorização,
  credenciais exclusivas e observabilidade;
- nenhum ambiente futuro pode reutilizar infraestrutura do Flowlog.
