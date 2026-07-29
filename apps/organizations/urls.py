from django.urls import path

from apps.organizations.views import organization_list

app_name = "organizations"

urlpatterns = [
    path("", organization_list, name="list"),
]
