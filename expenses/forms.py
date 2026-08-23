from django import forms

from .models import Expense, SupplierPayment


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ["category", "supplier", "date", "description", "amount",
                  "currency", "vat_percentage", "attachment"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "description": forms.TextInput(attrs={"class": "form-control"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "vat_percentage": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),
            "attachment": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name not in self.Meta.widgets:
                field.widget.attrs.setdefault("class", "form-select")


class SupplierPaymentForm(forms.ModelForm):
    class Meta:
        model = SupplierPayment
        fields = ["amount", "payment_date", "reference_number", "notes"]
        widgets = {
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01"}),
            "payment_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "reference_number": forms.TextInput(attrs={"class": "form-control"}),
            "notes": forms.TextInput(attrs={"class": "form-control"}),
        }
