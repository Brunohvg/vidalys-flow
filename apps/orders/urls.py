from django.urls import path

from apps.orders import quick_views, views

app_name = "orders"

urlpatterns = [
    path("", views.order_list, name="list"),
    path("new/", quick_views.order_create, name="create"),
    path("new/advanced/", views.order_create, name="create-draft"),
    path("<uuid:order_id>/", views.order_detail, name="detail"),
    path("<uuid:order_id>/customer/", views.order_change_customer, name="change-customer"),
    path("<uuid:order_id>/items/", views.order_add_item, name="add-item"),
    path("<uuid:order_id>/items/<uuid:item_id>/", views.order_update_item, name="update-item"),
    path("<uuid:order_id>/items/<uuid:item_id>/remove/", views.order_remove_item, name="remove-item"),
    path("<uuid:order_id>/confirm/", views.order_confirm, name="confirm"),
    path("<uuid:order_id>/cancel/", views.order_cancel, name="cancel"),
]
