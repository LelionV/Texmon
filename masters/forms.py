"""
Form machinery for the master-data CRUD UI.

ReasonModelForm adds a non-model `change_reason` field to whatever
ModelForm is generated for a given master model. It isn't saved onto the
model itself -- it's popped in the view and attached to the instance as
`_change_reason` immediately before `.save()`/`.delete()`, which is the
hook django-simple-history looks for to attach a reason to the resulting
HistoricalRecord. This is how "fields for reasons" (a note on *why* a
change was made) ends up attached to the audit history without needing a
separate visible column on the model itself.

build_master_form() generates one of these per registry entry on demand
(via Django's modelform_factory) rather than requiring a hand-written
ModelForm per master model -- consistent with the registry-driven approach
in masters/registry.py.
"""

from django import forms
from django.forms import modelform_factory


class ReasonModelForm(forms.ModelForm):
    change_reason = forms.CharField(
        required=False, max_length=200, label="Reason for this change",
        help_text="Optional, but recorded in this record's history for future reference.",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Updated after client confirmed new address"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name == "change_reason":
                continue
            if isinstance(field.widget, (forms.CheckboxInput,)):
                field.widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(field.widget, (forms.Select, forms.SelectMultiple)):
                field.widget.attrs.setdefault("class", "form-select")
            else:
                field.widget.attrs.setdefault("class", "form-control")


def build_master_form(entry):
    return modelform_factory(entry["model"], form=ReasonModelForm, fields=entry["fields"])
