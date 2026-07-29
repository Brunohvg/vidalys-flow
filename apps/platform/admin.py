from django.contrib import admin

from apps.platform.models import OutboxEvent

admin.site.register(OutboxEvent)
