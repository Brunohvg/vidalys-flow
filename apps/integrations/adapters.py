from dataclasses import dataclass

from .exceptions import IntegrationAmbiguousError, IntegrationPermanentError, IntegrationTransientError


@dataclass(frozen=True)
class AdapterResult:
    external_id: str
    result_code: str = "ok"


class ReferenceAdapter:
    """Deterministic offline adapter. It never performs network I/O."""

    key = "reference"

    def send(self, *, payload: dict, idempotency_key: str) -> AdapterResult:
        scenario = payload.get("scenario", "success")
        if scenario == "transient_failure":
            raise IntegrationTransientError("reference transient failure")
        if scenario == "permanent_failure":
            raise IntegrationPermanentError("reference permanent failure")
        if scenario in {"timeout", "ambiguous_acceptance"}:
            raise IntegrationAmbiguousError("reference ambiguous acceptance")
        return AdapterResult(external_id=f"ref-{idempotency_key[:24]}")

    def reconcile(self, *, external_id: str, payload: dict) -> AdapterResult:
        scenario = payload.get("reconcile_scenario", "success")
        if scenario == "uncertain":
            raise IntegrationAmbiguousError("reference reconciliation uncertain")
        if scenario == "permanent_failure":
            raise IntegrationPermanentError("reference reconciliation failed")
        return AdapterResult(external_id=external_id or "ref-reconciled", result_code="reconciled")


def get_adapter(key: str):
    if key != ReferenceAdapter.key:
        raise IntegrationPermanentError("adapter is not approved")
    return ReferenceAdapter()
