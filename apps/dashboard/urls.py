from django.urls import path

from apps.dashboard import views

app_name = "dashboard"

urlpatterns = [
    path("", views.dashboard_home, name="home"),
    path("pickups/", views.pickup_center, name="pickups"),
    path("reports/orders/", views.order_report, name="order-report"),
    path("reports/orders.csv", views.order_report_csv, name="order-report-csv"),
    path("orders/<uuid:order_id>/", views.order_workspace, name="order-workspace"),
]
