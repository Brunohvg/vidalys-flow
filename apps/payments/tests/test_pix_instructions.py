import pytest

from apps.audit.models import AuditEvent
from apps.payments.exceptions import PaymentPermissionDenied, VersionConflict
from apps.payments.models import PixPaymentInstruction
from apps.payments.pix_services import configure_pix_instruction, pix_instruction_for_order

pytestmark = pytest.mark.django_db


def test_manager_can_create_pix_instruction_without_raw_key_in_audit(
    organization,
    manager,
    manager_membership,
):
    instruction = configure_pix_instruction(
        organization=organization,
        actor=manager,
        key_type=PixPaymentInstruction.KeyType.EMAIL,
        key_value="Financeiro@Exemplo.com",
        beneficiary_name="Loja Exemplo",
        bank_name="Banco Exemplo",
    )

    assert instruction.key_value == "financeiro@exemplo.com"
    event = AuditEvent.objects.get(
        organization=organization,
        action="payment.pix_instruction_created",
    )
    assert event.payload == {
        "key_type": "email",
        "is_active": True,
        "version": 1,
    }
    assert instruction.key_value not in str(event.payload)


def test_operator_cannot_configure_pix_instruction(organization, user, operator_membership):
    with pytest.raises(PaymentPermissionDenied):
        configure_pix_instruction(
            organization=organization,
            actor=user,
            key_type=PixPaymentInstruction.KeyType.RANDOM,
            key_value="123e4567-e89b-12d3-a456-426614174000",
            beneficiary_name="Loja Exemplo",
        )


def test_pix_update_requires_expected_version(organization, manager, manager_membership):
    instruction = configure_pix_instruction(
        organization=organization,
        actor=manager,
        key_type=PixPaymentInstruction.KeyType.RANDOM,
        key_value="123e4567-e89b-12d3-a456-426614174000",
        beneficiary_name="Loja Exemplo",
    )

    with pytest.raises(VersionConflict):
        configure_pix_instruction(
            organization=organization,
            actor=manager,
            key_type=PixPaymentInstruction.KeyType.RANDOM,
            key_value="223e4567-e89b-12d3-a456-426614174000",
            beneficiary_name="Loja Exemplo",
            expected_version=instruction.version + 1,
        )


def test_pix_instruction_for_order_is_tenant_scoped(
    organization,
    other_organization,
    manager,
    manager_membership,
    payable_order,
):
    instruction = configure_pix_instruction(
        organization=organization,
        actor=manager,
        key_type=PixPaymentInstruction.KeyType.RANDOM,
        key_value="123e4567-e89b-12d3-a456-426614174000",
        beneficiary_name="Loja Exemplo",
    )

    assert pix_instruction_for_order(organization=organization, order=payable_order) == instruction
    assert pix_instruction_for_order(organization=other_organization, order=payable_order) is None
