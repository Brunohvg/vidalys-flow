# Dashboard and complete experience

## Purpose

Phase 08 adds an Organization-scoped operational read layer over the approved Vidalys Flow domains. It does not own a business lifecycle and does not create a persistence model.

The dashboard answers operational questions such as what needs attention now, which orders are active, and how an Order relates to its Payment, Fulfillment and transactional Messaging records. Canonical mutations remain in the owning domain.

## Organization boundary

Every dashboard selector receives an `Organization` resolved from the authenticated user's active `Membership`. Request data never chooses an arbitrary Organization. Cross-Organization records are filtered before composition, and a workspace request for an Order outside the active Organization returns 404.

## Read-model dependencies

- Orders provide the primary operational axis and recent-order list.
- Payments contribute `requires_attention` and `expired` work items plus the one-to-one PaymentIntent shown in an Order workspace.
- Fulfillment contributes open work in `draft`, `preparing`, `ready` and `in_transit`.
- Messaging contributes `failed` and `uncertain` transactional messages; an Order workspace includes messages whose canonical source is that Order.
- Integrations contributes degraded connections and `failed`/`uncertain` deliveries.

No dashboard state is written back into these domains, and no state is reinterpreted into a competing lifecycle.

## Attention queues

Attention queues are bounded operational lists. They are not inboxes, task models or workflow records. A queue item links users back to the owning canonical domain or to the read-only Order workspace.

The Phase 08 dashboard must not be expanded into an inbound WhatsApp sales inbox. Inbound sales conversations require a separately approved domain scope.

## Order workspace

The workspace composes an Organization-scoped Order with its Customer context, PaymentIntent, Fulfillments and directly sourced transactional Messages. It is read-only and provides navigation to canonical domain screens for details and authorized actions.

## Privacy

The dashboard exposes only fields needed for operational recognition. It must not expose provider credentials, webhook secrets, raw callback payloads, arbitrary integration metadata, complete private contact snapshots or other sensitive provider data.

## HTTP and persistence

Dashboard endpoints are authenticated `GET` views. There are no dashboard models or migrations. Actions continue through the owning domain, retaining that domain's authorization, idempotency and audit rules.

## External effects

Phase 08 performs no provider calls, sandbox access, public callbacks, credential activation, deploy, infrastructure provisioning, homologation or cutover.
