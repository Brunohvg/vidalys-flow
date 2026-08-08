from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect
from django.urls import include, path, reverse

from apps.users.forms import EmailAuthenticationForm


def root(request):
    if not request.user.is_authenticated:
        return redirect(f"{reverse('login')}?next={reverse('root')}")
    return redirect("organizations:list")


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
    path("health/", include("apps.platform.urls")),
    path("organizations/", include("apps.organizations.urls")),
    path("customers/", include("apps.customers.urls")),
    path("products/", include("apps.products.urls")),
    path("orders/", include("apps.orders.urls")),
    path(settings.ADMIN_PATH, admin.site.urls),
]
