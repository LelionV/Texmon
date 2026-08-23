"""
Lightweight JSON endpoints for masters data that the UI needs dynamically
(as opposed to full DRF ViewSets, which can be added later if an external
API consumer needs full CRUD).

- client_autofill: selecting a client on the quotation form auto-populates
  currency, payment terms, sales rep and billing info.
- item_autofill: selecting an item on a quotation/proforma/invoice line
  auto-populates that line's description, unit price and VAT percentage.
  The values are only a starting point -- every field they fill is a
  normal editable input, so price and VAT can still be adjusted by hand
  for that specific line without changing the master Item record.
"""

from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404

from .models import Client, Item


@login_required
def client_autofill(request, pk):
    client = get_object_or_404(Client, pk=pk, is_active=True)
    return JsonResponse(client.autofill_payload())


@login_required
def item_autofill(request, pk):
    item = get_object_or_404(Item, pk=pk, is_active=True)
    return JsonResponse({
        "code": item.code,
        "description": item.description or item.name,
        "unit_price": str(item.selling_price),
        "vat_percentage": str(item.vat_percentage) if item.vat_applicable else "0.00",
    })
