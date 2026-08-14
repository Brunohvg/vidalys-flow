from .models import IntegrationConnection, IntegrationDelivery


def connections_for_organization(organization):
    return IntegrationConnection.objects.filter(organization=organization).order_by("key")


def deliveries_for_organization(organization):
    return IntegrationDelivery.objects.filter(organization=organization).select_related("connection", "endpoint").order_by("-created_at")
