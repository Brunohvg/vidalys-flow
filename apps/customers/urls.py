from django.urls import path

from apps.customers import transfer_views, views

app_name = "customers"

urlpatterns = [
    path("", views.customer_list, name="list"),
    path("new/", views.customer_create, name="create"),
    path("import/", transfer_views.customer_import_csv, name="import-csv"),
    path("export.csv", transfer_views.customer_export_csv, name="export-csv"),
    path("<uuid:customer_id>/", views.customer_detail, name="detail"),
    path("<uuid:customer_id>/edit/", views.customer_edit, name="edit"),
    path("<uuid:customer_id>/contacts/", views.customer_add_contact, name="add-contact"),
    path("<uuid:customer_id>/addresses/", views.customer_add_address, name="add-address"),
    path("<uuid:customer_id>/notes/", views.customer_add_note, name="add-note"),
    path("<uuid:customer_id>/status/", views.customer_change_status, name="change-status"),
    path("<uuid:customer_id>/merge/", views.customer_merge, name="merge"),
]
