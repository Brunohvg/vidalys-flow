#!/usr/bin/env python3
"""Validate that scheduled Celery tasks are registered, routed, and consumed."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")

import django  # noqa: E402
from django.conf import settings  # noqa: E402

from config.celery import app as celery_app  # noqa: E402


def _worker_queues(command: str | Iterable[str] | None) -> set[str]:
    if command is None:
        return set()
    parts = command.split() if isinstance(command, str) else list(command)
    if "worker" not in parts:
        return set()
    queues: set[str] = set()
    for index, part in enumerate(parts):
        if part.startswith("--queues="):
            queues.update(filter(None, part.partition("=")[2].split(",")))
        elif part in {"--queues", "-Q"} and index + 1 < len(parts):
            queues.update(filter(None, parts[index + 1].split(",")))
    return queues


def _compose_worker_queues() -> set[str]:
    result = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    compose = json.loads(result.stdout)
    queues: set[str] = set()
    for service in compose.get("services", {}).values():
        queues.update(_worker_queues(service.get("command", [])))
    return queues


def main() -> int:
    django.setup()
    celery_app.loader.import_default_modules()

    routes = settings.CELERY_TASK_ROUTES
    scheduled_tasks = {entry["task"] for entry in settings.CELERY_BEAT_SCHEDULE.values()}
    routed_tasks = set(routes)
    registered_tasks = set(celery_app.tasks)
    missing_registration = sorted((scheduled_tasks | routed_tasks) - registered_tasks)

    routed_queues = {route["queue"] for route in routes.values()}
    declared_queues = {queue.name: queue for queue in settings.CELERY_TASK_QUEUES}
    consumed_queues = _compose_worker_queues()
    missing_declarations = sorted(routed_queues - set(declared_queues))
    missing_consumers = sorted(routed_queues - consumed_queues)
    bindings = [
        (queue.exchange.name, queue.routing_key)
        for queue in declared_queues.values()
        if queue.name in routed_queues
    ]
    ambiguous_bindings = len(bindings) != len(set(bindings))

    failures = []
    if missing_registration:
        failures.append(f"unregistered tasks: {', '.join(missing_registration)}")
    if missing_declarations:
        failures.append(f"undeclared queues: {', '.join(missing_declarations)}")
    if missing_consumers:
        failures.append(f"queues without Compose worker: {', '.join(missing_consumers)}")
    if ambiguous_bindings:
        failures.append("routed queues share an exchange/routing-key binding")
    if failures:
        print("ERROR: Celery runtime topology is incomplete: " + "; ".join(failures), file=sys.stderr)
        return 1

    print(
        "OK: Celery agenda/routes are registered and Compose consumes queues: "
        + ", ".join(sorted(consumed_queues))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
