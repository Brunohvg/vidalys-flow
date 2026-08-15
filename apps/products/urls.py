from django.urls import path

from apps.products import autocomplete_views, transfer_views, views

app_name = "products"

urlpatterns = [
    path("", views.product_list, name="list"),
    path("new/", views.product_create, name="create"),
    path("autocomplete/", autocomplete_views.product_autocomplete, name="autocomplete"),
    path("import/", transfer_views.product_import_csv, name="import-csv"),
    path("export.csv", transfer_views.product_export_csv, name="export-csv"),
    path("<uuid:product_id>/", views.product_detail, name="detail"),
    path("<uuid:product_id>/edit/", views.product_edit, name="edit"),
    path("<uuid:product_id>/variants/", views.product_add_variant, name="add-variant"),
    path("<uuid:product_id>/identifiers/", views.product_add_identifier, name="add-identifier"),
    path("<uuid:product_id>/status/", views.product_change_status, name="change-status"),
]
