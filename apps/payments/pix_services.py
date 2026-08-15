from django.db import transaction
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

from apps.audit.services import record_event
from apps.customers.normalization import normalize_document, normalize_email, normalize_phone
from apps.payments import policies
from apps.payments.exceptions import InvalidPayment, PaymentPermissionDenied, VersionConflict
from apps.payments.models import PixPaymentInstruction


def _require_manager(*, actor, organization):
    if not policies.can_operate_payments(user=actor, organization=organization):
        raise PaymentPermissionDenied("Membership ativa de manager tier é obrigatória.")


def _normalize_key(*, key_type, key_value):
    value = (key_value or "").strip()
    if not value:
        raise InvalidPayment("Informe a chave PIX.")

    if key_type in {PixPaymentInstruction.KeyType.CPF, PixPaymentInstruction.KeyType.CNPJ}:
        try:
            normalized = normalize_document(value)
        except ValueError as exc:
            raise InvalidPayment(str(exc)) from exc
        expected_length = 11 if key_type == PixPaymentInstruction.KeyType.CPF else 14
        if len(normalized) != expected_length:
            raise InvalidPayment("O tipo da chave PIX não corresponde ao documento informado.")
        return normalized

    if key_type == PixPaymentInstruction.KeyType.EMAIL:
        normalized = normalize_email(value)
        try:
            validate_email(normalized)
        except ValidationError as exc:
            raise InvalidPayment("E-mail PIX inválido.") from exc
        return normalized

    if key_type == PixPaymentInstruction.KeyType.PHONE:
        normalized = normalize_phone(value)
        if len(normalized) < 12:
            raise InvalidPayment("Telefone PIX inválido.")
        return normalized

    if key_type == PixPaymentInstruction.KeyType.RANDOM:
        if len(value) > 160:
            raise InvalidPayment("Chave PIX aleatória excede o limite permitido.")
        return value

    raise InvalidPayment("Tipo de chave PIX inválido.")


@transaction.atomic
def configure_pix_instruction(
    *,
    organization,
    actor,
    key_type,
    key_value,
    beneficiary_name,
    bank_name="",
    is_active=True,
    expected_version=None,
):
    _require_manager(actor=actor, organization=organization)
    normalized_key = _normalize_key(key_type=key_type, key_value=key_value)
    beneficiary_name = (beneficiary_name or "").strip()
    if not beneficiary_name:
        raise InvalidPayment("Informe o favorecido do PIX.")

    current = PixPaymentInstruction.objects.select_for_update().filter(organization=organization).first()
    if current is None:
        if expected_version not in (None, 0):
            raise VersionConflict("Configuração PIX ainda não existe.")
        instruction = PixPaymentInstruction.objects.create(
            organization=organization,
            key_type=key_type,
            key_value=normalized_key,
            beneficiary_name=beneficiary_name,
            bank_name=(bank_name or "").strip(),
            is_active=bool(is_active),
            updated_by=actor,
        )
        action = "payment.pix_instruction_created"
    else:
        if expected_version is None or current.version != expected_version:
            raise VersionConflict(
                f"Configuração PIX alterada (versão atual {current.version}, recebida {expected_version})."
            )
        current.key_type = key_type
        current.key_value = normalized_key
        current.beneficiary_name = beneficiary_name
        current.bank_name = (bank_name or "").strip()
        current.is_active = bool(is_active)
        current.updated_by = actor
        current.version += 1
        current.save(
            update_fields=(
                "key_type",
                "key_value",
                "beneficiary_name",
                "bank_name",
                "is_active",
                "updated_by",
                "version",
                "updated_at",
            )
        )
        instruction = current
        action = "payment.pix_instruction_updated"

    record_event(
        organization=organization,
        actor=actor,
        action=action,
        entity_type="pix_payment_instruction",
        entity_id=instruction.id,
        payload={
            "key_type": instruction.key_type,
            "is_active": instruction.is_active,
            "version": instruction.version,
        },
    )
    return instruction


def pix_instruction_for_order(*, organization, order):
    if order.organization_id != organization.id:
        return None
    return PixPaymentInstruction.objects.filter(organization=organization, is_active=True).first()
