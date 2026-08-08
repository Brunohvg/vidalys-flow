# PR Draft: Implement Fulfillment domain (phase/04)

Branch: `work/phase-04-fulfillment-001`

Summary
- Adds initial Fulfillment domain scaffolding: models, items, immutable status history, and idempotency receipts.
- Implements `create_fulfillment` service with validation, idempotency, audit recording and outbox enqueue.
- Adds initial unit test for idempotent creation and an initial migration.

Files changed
- `apps/fulfillment/models.py`
- `apps/fulfillment/services.py`
- `apps/fulfillment/idempotency.py`
- `apps/fulfillment/exceptions.py`
- `apps/fulfillment/migrations/0001_initial.py`
- `apps/fulfillment/tests/test_services.py`
- `config/settings/base.py`

Acceptance checklist (PR author completes before requesting merge)
- [ ] `project/handoffs/phase-04.json` attached and accurate
- [ ] All tests pass in CI (PostgreSQL 17, coverage >= project requirement)
- [ ] `scripts/check_secrets.py` and `scripts/check_independence.py` pass in CI
- [ ] `ruff` and `Django check` pass in CI
- [ ] No PII or free-text in audit/outbox logs (sanitization verified)
- [ ] Migration applies cleanly on empty PostgreSQL 17 and supports technical rollback
- [ ] Independent code review completed (no unresolved blockers)
- [ ] Add explicit human approval (name + timestamp) in handoff before merge

Reviewer notes
- The implementation intentionally delays model imports in service/idempotency helpers to avoid app registry import-time issues.
- Running tests locally encountered differences between the runtime image and dev image; CI will run the canonical pipeline and must be used to validate migrations and full test suite.

Suggested commands to reproduce locally (dev image)
```bash
# Build test image with dev deps (if not using compose dev profile)
docker compose build --pull
docker compose run --rm migrate
docker compose exec web .venv/bin/python -m pytest -q
```

Handoff: `project/handoffs/phase-04.json` created — please add explicit approver before merge.
