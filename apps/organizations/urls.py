from django.urls import path

from apps.organizations.views import organization_list, select_organization

app_name = "organizations"

urlpatterns = [
    path("", organization_list, name="list"),
    path("<uuid:organization_id>/select/", select_organization, name="select"),
]
