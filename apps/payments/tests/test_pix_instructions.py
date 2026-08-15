import pytest

from apps.audit.models import AuditEvent
from apps.payments.exceptions import InvalidPayment, PaymentPermissionDenied, VersionConflict
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
        "key_type": "[REDACTED]",
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


def test_pix_normalizes_document_phone_and_email_keys(organization, manager, manager_membership):
    cpf = configure_pix_instruction(
        organization=organization,
        actor=manager,
        key_type=PixPaymentInstruction.KeyType.CPF,
        key_value="529.982.247-25",
        beneficiary_name="Pessoa",
    )
    assert cpf.key_value == "52998224725"

    cnpj = configure_pix_instruction(
        organization=organization,
        actor=manager,
        key_type=PixPaymentInstruction.KeyType.CNPJ,
        key_value="11.222.333/0001-81",
        beneficiary_name="Empresa",
        expected_version=cpf.version,
    )
    assert cnpj.key_value == "11222333000181"

    phone = configure_pix_instruction(
        organization=organization,
        actor=manager,
        key_type=PixPaymentInstruction.KeyType.PHONE,
        key_value="(11) 99999-9999",
        beneficiary_name="Empresa",
        expected_version=cnpj.version,
    )
    assert phone.key_value == "+5511999999999"

    email = configure_pix_instruction(
        organization=organization,
        actor=manager,
        key_type=PixPaymentInstruction.KeyType.EMAIL,
        key_value=" PAGAMENTOS@EXAMPLE.COM ",
        beneficiary_name="Empresa",
        expected_version=phone.version,
    )
    assert email.key_value == "pagamentos@example.com"
    assert email.version == 4
    assert AuditEvent.objects.filter(
        organization=organization,
        action="payment.pix_instruction_updated",
    ).count() == 3


def test_pix_rejects_invalid_key_shapes_and_beneficiary(organization, manager, manager_membership):
    cases = [
        (PixPaymentInstruction.KeyType.CPF, "", "Informe a chave PIX"),
        (PixPaymentInstruction.KeyType.CPF, "123", "CPF ou CNPJ válido"),
        (PixPaymentInstruction.KeyType.CPF, "11.222.333/0001-81", "não corresponde"),
        (PixPaymentInstruction.KeyType.EMAIL, "not-an-email", "E-mail PIX inválido"),
        (PixPaymentInstruction.KeyType.PHONE, "123", "Telefone PIX inválido"),
        (PixPaymentInstruction.KeyType.RANDOM, "x" * 161, "excede o limite"),
        ("unsupported", "value", "Tipo de chave PIX inválido"),
    ]
    for key_type, value, message in cases:
        with pytest.raises(InvalidPayment, match=message):
            configure_pix_instruction(
                organization=organization,
                actor=manager,
                key_type=key_type,
                key_value=value,
                beneficiary_name="Favorecido",
            )

    with pytest.raises(InvalidPayment, match="favorecido"):
        configure_pix_instruction(
            organization=organization,
            actor=manager,
            key_type=PixPaymentInstruction.KeyType.RANDOM,
            key_value="random-key",
            beneficiary_name="   ",
        )


def test_pix_update_requires_expected_version(organization, manager, manager_membership):
    with pytest.raises(VersionConflict, match="ainda não existe"):
        configure_pix_instruction(
            organization=organization,
            actor=manager,
            key_type=PixPaymentInstruction.KeyType.RANDOM,
            key_value="new-key",
            beneficiary_name="Loja Exemplo",
            expected_version=2,
        )

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


def test_pix_instruction_for_order_is_tenant_scoped_and_active_only(
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

    configure_pix_instruction(
        organization=organization,
        actor=manager,
        key_type=PixPaymentInstruction.KeyType.RANDOM,
        key_value="123e4567-e89b-12d3-a456-426614174000",
        beneficiary_name="Loja Exemplo",
        is_active=False,
        expected_version=instruction.version,
    )
    assert pix_instruction_for_order(organization=organization, order=payable_order) is None
