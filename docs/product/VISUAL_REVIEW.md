# Vidalys Flow — Phase 10 Visual Review

## Checkpoint

This document records the human visual-review checkpoint for Phase 10 — Product Experience Completion.

Visual candidate SHA: `3459ce001fb57b02901f09d7d2fdd5fde449f386`

The candidate is functionally validated by Foundation CI #390. This checkpoint does not constitute Independent Review, QA/Security, phase approval, merge authorization, deploy authorization, provider activation or cutover authorization.

## Review purpose

The goal is to verify that the implemented experience is visually clear, coherent and operational while preserving the canonical domain contracts already validated by CI.

The human reviewer may approve the candidate as-is or request visual/UX rework within the approved Phase 10 margin.

## Critical screens to review

1. Authentication/login shell.
2. Dashboard.
3. Orders list and operational presets.
4. Quick Order creation.
5. Order detail / Order Workspace and `Próxima ação`.
6. Payments detail, manual payment and Organization PIX settings.
7. Fulfillment creation and detail.
8. Pickup Center and secure pickup confirmation.
9. Customers list/detail/import/export.
10. Products list/detail/import/export.
11. Reports, comparison and custom range.
12. Global search / operational quick search.
13. Messaging and Integrations navigation continuity.
14. Profile.
15. Team/users.
16. Settings hub.
17. Audit.
18. Organization selection.
19. Responsive behavior on desktop, tablet and mobile.

## Visual acceptance criteria

The reviewer should confirm that:

- the common path is visually the shortest path;
- the grouped navigation is understandable without training;
- `Próxima ação` is visually dominant when a next operational action exists;
- Quick Order keeps customer + value as the primary path and leaves optional data progressive;
- payment, fulfillment and messaging remain visually distinct instead of appearing as one merged lifecycle;
- destructive or irreversible actions are visually differentiated from ordinary actions;
- status is never communicated by color alone;
- tables remain usable at operational density;
- empty states explain what to do next;
- forms keep labels, focus states and validation understandable;
- mobile layouts preserve the important actions without horizontal dependency;
- PII visibility remains consistent with role permissions;
- administrative surfaces are visually separated from daily operation;
- the visual language feels like Vidalys Flow rather than Flowlog or a generic ERP.

## Brand review

The current product shell uses the approved violet/indigo visual direction and the text brand `Vidalys Flow`.

The current CSS `V` mark is a temporary product mark and is not the frozen final logo.

The final brand review must cover:

- symbol proposal based on a distinctive V / flow-ribbon concept;
- horizontal wordmark `Vidalys Flow`;
- compact lockup;
- app icon / favicon;
- light and dark variants;
- monochrome variant;
- legibility at small sizes;
- final primary and secondary brand tokens;
- final typography decision.

No logo proposal becomes canonical until explicit human visual acceptance.

## Rework allowed without scope expansion

The following may be changed during this checkpoint without opening a new product scope:

- navigation grouping and labels;
- position and hierarchy of cards;
- spacing, radius and shadow;
- typography and font stack;
- secondary colors;
- button wording and placement;
- dashboard composition;
- report presentation;
- Pickup Center layout;
- Quick Order visual composition;
- responsive layout;
- brand symbol, wordmark and lockups.

The following are not visual-only changes and remain protected by the approved functional contract:

- Organization isolation;
- authorization;
- PII masking;
- idempotency;
- canonical money source;
- Orders / Payments / Fulfillment / Messaging lifecycle separation;
- provider-effect guardrails;
- audit sanitization.

## Human decision

Status: `pending`

Allowed outcomes:

- `VISUAL_ACCEPTED` — the visual candidate may proceed to implementation closeout and handoff preparation.
- `VISUAL_REWORK_REQUESTED` — implement only the requested visual/UX changes, rerun the full regression suite and present a new visual candidate SHA.

Independent Review and QA/Security must not begin until this checkpoint is resolved.
