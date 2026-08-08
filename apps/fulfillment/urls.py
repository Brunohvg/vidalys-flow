from django.urls import path

from apps.fulfillment import views

app_name = "fulfillment"

urlpatterns = [
    path("", views.fulfillment_list, name="list"),
    path("orders/<uuid:order_id>/new/", views.fulfillment_create, name="create"),
    path("<uuid:fulfillment_id>/", views.fulfillment_detail, name="detail"),
    path("<uuid:fulfillment_id>/items/", views.fulfillment_update, name="update"),
    path(
        "<uuid:fulfillment_id>/transition/<str:target_status>/",
        views.fulfillment_transition,
        name="transition",
    ),
    path("<uuid:fulfillment_id>/cancel/", views.fulfillment_cancel, name="cancel"),
]
