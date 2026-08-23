from django import forms

from masters.models import Client


class GenerateStatementForm(forms.Form):
    client = forms.ModelChoiceField(queryset=Client.objects.filter(is_active=True), widget=forms.Select(attrs={"class": "form-select"}))
    date_from = forms.DateField(widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))
    date_to = forms.DateField(widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}))

    def clean(self):
        cleaned = super().clean()
        date_from, date_to = cleaned.get("date_from"), cleaned.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise forms.ValidationError("'Date From' must be on or before 'Date To'.")
        return cleaned
