from django.urls import path

from apps.fulfillment import pickup_views, views, workspace_views

app_name = "fulfillment"

urlpatterns = [
    path("", views.fulfillment_list, name="list"),
    path("orders/<uuid:order_id>/new/", views.fulfillment_create, name="create"),
    path("<uuid:fulfillment_id>/", views.fulfillment_detail, name="detail"),
    path("<uuid:fulfillment_id>/items/", views.fulfillment_update, name="update"),
    path("<uuid:fulfillment_id>/tracking/", views.fulfillment_tracking, name="tracking"),
    path(
        "<uuid:fulfillment_id>/workspace/tracking/",
        workspace_views.workspace_tracking,
        name="workspace_tracking",
    ),
    path(
        "<uuid:fulfillment_id>/transition/<str:target_status>/",
        views.fulfillment_transition,
        name="transition",
    ),
    path(
        "<uuid:fulfillment_id>/workspace/transition/<str:target_status>/",
        workspace_views.workspace_transition,
        name="workspace_transition",
    ),
    path("<uuid:fulfillment_id>/pickup/complete/", pickup_views.complete_pickup, name="complete_pickup"),
    path("<uuid:fulfillment_id>/cancel/", views.fulfillment_cancel, name="cancel"),
]
