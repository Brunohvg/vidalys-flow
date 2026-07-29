from django.urls import path

from apps.platform.views import liveness, readiness

app_name = "platform"

urlpatterns = [
    path("live/", liveness, name="live"),
    path("ready/", readiness, name="ready"),
]
