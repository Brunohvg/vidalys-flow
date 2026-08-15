from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect
from django.urls import include, path, reverse

from apps.users.forms import EmailAuthenticationForm


def root(request):
    if not request.user.is_authenticated:
        return redirect(f"{reverse('login')}?next={reverse('root')}")
    return redirect("dashboard:home")


urlpatterns = [
    path("", root, name="root"),
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="auth/login.html",
            authentication_form=EmailAuthenticationForm,
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "account/password/",
        auth_views.PasswordChangeView.as_view(
            template_name="auth/password_change.html",
            success_url="/account/password/done/",
        ),
        name="password_change",
    ),
    path(
        "account/password/done/",
        auth_views.PasswordChangeDoneView.as_view(template_name="auth/password_change_done.html"),
        name="password_change_done",
    ),
    path("health/", include("apps.platform.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    path("account/", include("apps.users.urls")),
    path("organizations/", include("apps.organizations.urls")),
    path("customers/", include("apps.customers.urls")),
    path("products/", include("apps.products.urls")),
    path("orders/", include("apps.orders.urls")),
    path("fulfillment/", include("apps.fulfillment.urls")),
    path("payments/", include("apps.payments.urls")),
    path("messaging/", include("apps.messaging.urls")),
    path("integrations/", include("apps.integrations.urls")),
    path(settings.ADMIN_PATH, admin.site.urls),
]
