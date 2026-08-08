# Phase 05 — Payments (planning)

Status: candidate

Goals
- Implement Payments domain with gateways, captures, refunds and reconciliation.
- Provide adapters to external providers with clear interfaces and sandbox integration.

Initial checklist
- [ ] Define models and events for payments and transactions
- [ ] Design gateway adapter interface and one reference implementation
- [ ] Add tests and migrations; validate on empty PostgreSQL 17
- [ ] Add security review and QA checkpoints to pipeline
- [ ] Create handoff file `project/handoffs/phase-05.json` when ready

Notes
- Start with an internal-only sandbox gateway adapter for local dev and CI.
- Coordinate with Finance for reconciliation requirements.
