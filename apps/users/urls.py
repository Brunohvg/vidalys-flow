from django.urls import path

from apps.users import phase10_views

app_name = "users"

urlpatterns = [
    path("profile/", phase10_views.profile, name="profile"),
    path("team/", phase10_views.team, name="team"),
    path("team/<uuid:membership_id>/", phase10_views.team_update, name="team-update"),
]
