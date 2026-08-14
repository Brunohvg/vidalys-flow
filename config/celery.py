import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")

app = Celery("vidalys_flow")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks(
    [
        "apps.core",
        "apps.users",
        "apps.organizations",
        "apps.audit",
        "apps.platform",
        "apps.customers",
        "apps.products",
        "apps.orders",
        "apps.fulfillment",
        "apps.payments",
        "apps.messaging",
        "apps.integrations",
    ]
)
