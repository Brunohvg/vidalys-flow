import uuid
from decimal import Decimal

from django import forms

from apps.fulfillment.models import Fulfillment
from apps.orders.models import Order
from apps.organizations.models import OrganizationUnit


class FulfillmentFilterForm(forms.Form):
    q = forms.CharField(required=False, label="Busca")
    status = forms.ChoiceField(
        required=False,
        choices=(("", "Todos"), *Fulfillment.Status.choices),
        label="Estado",
    )
    method = forms.ChoiceField(
        required=False,
        choices=(("", "Todos"), *Fulfillment.Method.choices),
        label="Método",
    )


class AllocationForm(forms.Form):
    expected_version = forms.IntegerField(min_value=1, required=False, widget=forms.HiddenInput)
    idempotency_key = forms.CharField(max_length=64, widget=forms.HiddenInput)

    def __init__(self, *args, order, initial_allocations=None, **kwargs):
        super().__init__(*args, **kwargs)
        initial_allocations = initial_allocations or {}
        self.order_items = list(order.items.order_by("position"))
        self.allow_empty_allocations = order.pricing_mode == Order.PricingMode.MANUAL and not self.order_items
        for item in self.order_items:
            field_name = f"quantity_{item.id}"
            self.fields[field_name] = forms.DecimalField(
                max_digits=12,
                decimal_places=3,
                min_value=Decimal("0.001"),
                max_value=item.quantity,
                required=False,
                label=f"{item.position}. {item.name_snapshot} (máx. {item.quantity} {item.unit_snapshot})",
                initial=initial_allocations.get(item.id),
            )
        if not self.is_bound:
            self.initial.setdefault("idempotency_key", str(uuid.uuid4()))

    def clean(self):
        cleaned = super().clean()
        allocations = []
        for name, value in cleaned.items():
            if name.startswith("quantity_") and value is not None:
                item_id = name.removeprefix("quantity_")
                item = next(item for item in self.order_items if str(item.id) == item_id)
                allocations.append({"order_item": item, "quantity": value})
        if not allocations and not self.allow_empty_allocations:
            raise forms.ValidationError("Informe ao menos uma quantidade.")
        cleaned["allocations"] = allocations
        return cleaned


class FulfillmentCreateForm(AllocationForm):
    method = forms.ChoiceField(choices=Fulfillment.Method.choices, label="Método")
    pickup_unit = forms.ModelChoiceField(
        queryset=OrganizationUnit.objects.none(),
        required=False,
        label="Unidade de retirada",
    )

    def __init__(self, *args, organization, order, **kwargs):
        super().__init__(*args, order=order, **kwargs)
        self.fields["pickup_unit"].queryset = OrganizationUnit.objects.filter(
            organization=organization,
            is_active=True,
        )
        self.fields.pop("expected_version")

    def clean(self):
        cleaned = super().clean()
        method = cleaned.get("method")
        unit = cleaned.get("pickup_unit")
        if method == Fulfillment.Method.PICKUP and unit is None:
            self.add_error("pickup_unit", "Retirada exige uma unidade ativa.")
        if method == Fulfillment.Method.DELIVERY and unit is not None:
            self.add_error("pickup_unit", "Entrega não utiliza unidade de retirada.")
        return cleaned


class FulfillmentAllocationForm(AllocationForm):
    pass


class TransitionForm(forms.Form):
    expected_version = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    idempotency_key = forms.CharField(max_length=64, widget=forms.HiddenInput)

    @staticmethod
    def command_initial(*, version):
        return {"expected_version": version, "idempotency_key": str(uuid.uuid4())}


class CancelForm(TransitionForm):
    reason = forms.CharField(max_length=500, label="Motivo", widget=forms.Textarea(attrs={"rows": 3}))
