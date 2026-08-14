from django.urls import path

from apps.messaging import views

app_name = "messaging"

urlpatterns = [
    path("send/", views.message_send, name="send"),
    path("connections/", views.connection_list, name="connection_list"),
    path("connections/<uuid:connection_id>/<str:action>/", views.connection_state, name="connection_state"),
    path("channels/", views.channel_list, name="channel_list"),
    path("channels/<uuid:channel_id>/activate/", views.channel_activate, name="channel_activate"),
    path("channels/<uuid:channel_id>/disable/", views.channel_disable, name="channel_disable"),
    path("channels/<uuid:channel_id>/pair/", views.channel_pair, name="channel_pair"),
    path("templates/", views.template_list, name="template_list"),
    path("rules/", views.rule_list, name="rule_list"),
    path("preferences/", views.preference_create, name="preference_create"),
    path("callbacks/<uuid:channel_id>/", views.delivery_callback, name="delivery_callback"),
    path("", views.message_list, name="list"),
    path("<uuid:message_id>/", views.message_detail, name="detail"),
    path("<uuid:message_id>/cancel/", views.message_cancel, name="cancel"),
]
