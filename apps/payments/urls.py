from django.urls import path

from apps.payments import manual_views, views

app_name = "payments"

urlpatterns = [
    path(
        "callbacks/<uuid:provider_account_id>/mercado-pago/",
        views.mercado_pago_callback,
        name="mercado_pago_callback",
    ),
    path("", views.payment_list, name="list"),
    path("orders/<uuid:order_id>/new/", views.payment_create, name="create"),
    path("<uuid:payment_id>/", views.payment_detail, name="detail"),
    path("<uuid:payment_id>/manual/", manual_views.payment_confirm_manual, name="confirm_manual"),
    path("<uuid:payment_id>/checkout/", views.payment_request_checkout, name="request_checkout"),
    path("<uuid:payment_id>/checkout/cancel/", views.payment_cancel_checkout, name="cancel_checkout"),
    path("<uuid:payment_id>/reopen/", views.payment_reopen, name="reopen"),
]
