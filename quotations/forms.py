"""
Quotation header form + a QuotationItem inline formset.

QuotationItemFormSet uses inlineformset_factory with can_delete=True so the
create/edit template can render an HTMX-friendly "add another line" /
"remove" UI, matching the spec's requirement for dynamic quotation items.
"""

from django import forms
from django.forms import inlineformset_factory

from .models import Quotation, QuotationItem


class QuotationForm(forms.ModelForm):
    class Meta:
        model = Quotation
        fields = [
            "client", "date", "valid_until", "shipment_type", "currency", "payment_terms",
            "sales_representative", "origin_port", "destination_port",
            "final_destination", "commodity", "commodity_quantity", "commodity_unit",
            "reference_document", "notes", "terms",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "valid_until": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "notes": forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
            "terms": forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
            "commodity": forms.TextInput(attrs={
                "class": "form-control", "list": "commodity-suggestions",
                "placeholder": "e.g. Flowers, Machinery, Electronics ...", "autocomplete": "off",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name not in self.Meta.widgets:
                css = "form-select" if isinstance(field.widget, forms.Select) else "form-control"
                field.widget.attrs.setdefault("class", css)
        if not self.instance.pk:
            # Default terms/validity from Document Settings for new quotations.
            from masters.models import DocumentSettings
            settings_obj = DocumentSettings.get_solo()
            self.fields["terms"].initial = settings_obj.quotation_terms


class QuotationItemForm(forms.ModelForm):
    class Meta:
        model = QuotationItem
        fields = ["item", "description", "quantity", "unit_price", "vat_percentage"]
        widgets = {
            "description": forms.TextInput(attrs={"class": "form-control", "placeholder": "Description"}),
            "quantity": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "unit_price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "vat_percentage": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "item": forms.Select(attrs={"class": "form-select item-select"}),
        }


QuotationItemFormSet = inlineformset_factory(
    Quotation, QuotationItem, form=QuotationItemForm,
    extra=1, can_delete=True, min_num=1, validate_min=True,
)
