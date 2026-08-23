"""
Proforma header form + line-item formset. The header form deliberately
excludes `client`/`currency`/`payment_terms`/`quotation` etc. from being
editable through the UI (they're copied at conversion time and shouldn't
drift from what was actually quoted) -- only the proforma-specific shipping
fields and the line items are editable here, all while status == Draft.
"""

from django import forms
from django.forms import inlineformset_factory

from .models import ProformaInvoice, ProformaInvoiceItem


class ProformaInvoiceForm(forms.ModelForm):
    class Meta:
        model = ProformaInvoice
        fields = [
            "date", "bl_number", "shipment_reference", "container_number",
            "vessel", "eta", "etd", "notes", "terms",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "eta": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "etd": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "notes": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "terms": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name not in self.Meta.widgets:
                field.widget.attrs.setdefault("class", "form-control")


class ProformaInvoiceItemForm(forms.ModelForm):
    class Meta:
        model = ProformaInvoiceItem
        fields = ["item", "description", "quantity", "unit_price", "vat_percentage"]
        widgets = {
            "description": forms.TextInput(attrs={"class": "form-control"}),
            "quantity": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "unit_price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "vat_percentage": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "item": forms.Select(attrs={"class": "form-select"}),
        }


ProformaInvoiceItemFormSet = inlineformset_factory(
    ProformaInvoice, ProformaInvoiceItem, form=ProformaInvoiceItemForm,
    extra=0, can_delete=True, min_num=1, validate_min=True,
)
