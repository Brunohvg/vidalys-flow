from django.urls import path

from apps.payments import manual_views, pix_views, views, workspace_views

app_name = "payments"

urlpatterns = [
    path(
        "callbacks/<uuid:provider_account_id>/mercado-pago/",
        views.mercado_pago_callback,
        name="mercado_pago_callback",
    ),
    path("", views.payment_list, name="list"),
    path("settings/pix/", pix_views.pix_settings, name="pix_settings"),
    path("orders/<uuid:order_id>/new/", views.payment_create, name="create"),
    path(
        "orders/<uuid:order_id>/workspace/create/",
        workspace_views.workspace_create_payment,
        name="workspace_create",
    ),
    path("<uuid:payment_id>/", views.payment_detail, name="detail"),
    path("<uuid:payment_id>/manual/", manual_views.payment_confirm_manual, name="confirm_manual"),
    path(
        "<uuid:payment_id>/workspace/manual/",
        workspace_views.workspace_confirm_manual,
        name="workspace_manual",
    ),
    path("<uuid:payment_id>/checkout/", views.payment_request_checkout, name="request_checkout"),
    path(
        "<uuid:payment_id>/workspace/checkout/",
        workspace_views.workspace_request_checkout,
        name="workspace_checkout",
    ),
    path("<uuid:payment_id>/checkout/cancel/", views.payment_cancel_checkout, name="cancel_checkout"),
    path(
        "<uuid:payment_id>/workspace/checkout/cancel/",
        workspace_views.workspace_cancel_checkout,
        name="workspace_cancel_checkout",
    ),
    path("<uuid:payment_id>/reopen/", views.payment_reopen, name="reopen"),
]
