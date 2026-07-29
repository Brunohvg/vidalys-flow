from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from apps.organizations.exceptions import BootstrapConflictError, LastActiveOwnerError
from apps.organizations.models import Membership, Organization, OrganizationUnit


@dataclass(frozen=True)
class BootstrapResult:
    user: object
    organization: Organization
    membership: Membership
    unit: OrganizationUnit
    created: bool


@transaction.atomic
def deactivate_membership(*, membership):
    locked_organization = Organization.objects.select_for_update().get(pk=membership.organization_id)
    locked = Membership.objects.select_for_update().get(pk=membership.pk)
    if not locked.is_active:
        return locked
    if locked.role == Membership.Role.OWNER:
        active_owner_count = Membership.objects.filter(
            organization=locked_organization,
            role=Membership.Role.OWNER,
            is_active=True,
        ).count()
        if active_owner_count <= 1:
            raise LastActiveOwnerError("A organização deve manter pelo menos um OWNER ativo.")
    locked.is_active = False
    locked.save(update_fields=("is_active", "updated_at"))
    return locked


@transaction.atomic
def bootstrap_organization(*, organization_name, slug, owner_email, owner_name, unit_name):
    User = get_user_model()
    normalized_email = User.objects.normalize_identity(owner_email)
    normalized_name = organization_name.strip()
    normalized_slug = slug.strip().lower()
    normalized_unit_name = unit_name.strip()
    owner_parts = owner_name.strip().split(maxsplit=1)
    first_name = owner_parts[0] if owner_parts else ""
    last_name = owner_parts[1] if len(owner_parts) > 1 else ""

    if not all((normalized_name, normalized_slug, normalized_email, first_name, normalized_unit_name)):
        raise BootstrapConflictError("Todos os dados do bootstrap são obrigatórios.")

    organization = Organization.objects.select_for_update().filter(slug__iexact=normalized_slug).first()
    user = User.objects.filter(email__iexact=normalized_email).first()
    created = organization is None and user is None

    if organization is None:
        organization = Organization.objects.create(name=normalized_name, slug=normalized_slug)
    elif organization.name != normalized_name:
        raise BootstrapConflictError("O slug já pertence a uma organização com outro nome.")

    if user is None:
        user = User.objects.create_user(
            email=normalized_email,
            password=None,
            first_name=first_name,
            last_name=last_name,
        )
    elif not user.is_active:
        raise BootstrapConflictError("O e-mail informado pertence a um usuário inativo.")

    try:
        membership, membership_created = Membership.objects.get_or_create(
            organization=organization,
            user=user,
            defaults={"role": Membership.Role.OWNER, "is_active": True},
        )
        if not membership_created and (
            membership.role != Membership.Role.OWNER or not membership.is_active
        ):
            raise BootstrapConflictError("A Membership existente não é um OWNER ativo.")
        unit, _ = OrganizationUnit.objects.get_or_create(
            organization=organization,
            name=normalized_unit_name,
        )
    except IntegrityError as exc:
        raise BootstrapConflictError("Conflito concorrente durante o bootstrap.") from exc

    return BootstrapResult(
        user=user,
        organization=organization,
        membership=membership,
        unit=unit,
        created=created,
    )
