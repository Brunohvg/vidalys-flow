from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


def database_status():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return "ok"


def cache_status():
    key = "vidalys_flow:health:ready"
    cache.set(key, "ok", timeout=10)
    if cache.get(key) != "ok":
        raise RuntimeError("Falha de leitura no cache.")
    cache.delete(key)
    return "ok"


def migrations_status():
    executor = MigrationExecutor(connection)
    targets = executor.loader.graph.leaf_nodes()
    if executor.migration_plan(targets):
        raise RuntimeError("Existem migrations pendentes.")
    return "ok"


def configuration_status():
    if not settings.SECRET_KEY:
        raise RuntimeError("SECRET_KEY ausente.")
    if connection.vendor != "postgresql":
        raise RuntimeError("PostgreSQL é obrigatório.")
    return "ok"


def readiness_report():
    checks = {
        "database": database_status,
        "redis": cache_status,
        "migrations": migrations_status,
        "configuration": configuration_status,
    }
    report = {}
    healthy = True
    for name, check in checks.items():
        try:
            report[name] = check()
        except Exception:  # noqa: BLE001
            report[name] = "unavailable"
            healthy = False
    return healthy, report
