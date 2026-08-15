from django.urls import path

from apps.dashboard import views

app_name = "dashboard"

urlpatterns = [
    path("", views.dashboard_home, name="home"),
    path("pickups/", views.pickup_center, name="pickups"),
    path("orders/<uuid:order_id>/", views.order_workspace, name="order-workspace"),
]
