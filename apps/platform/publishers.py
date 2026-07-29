from dataclasses import dataclass

from apps.platform.guardrails import require_external_effects_allowed


@dataclass(frozen=True)
class PublishResult:
    accepted: bool


class DummyOutboxPublisher:
    external = False

    def publish(self, event):
        return PublishResult(accepted=True)


def publish_event(*, event, publisher):
    if getattr(publisher, "external", True):
        require_external_effects_allowed()
    return publisher.publish(event)
