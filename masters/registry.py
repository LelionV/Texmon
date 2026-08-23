"""
Registry-driven configuration for the master-data CRUD UI.

Rather than hand-writing near-identical ListView/CreateView/UpdateView/
DeleteView/HistoryView + templates for each of Client, Supplier, Currency,
PaymentTerm, Commodity, Item, Port, and Transporter, every one of those
models is described once here (which fields are editable, which columns
show in the list, which fields are searchable) and a single set of generic
views + templates (masters/views.py, templates/masters/master_*.html)
renders all of them. Adding a new master-data model to the custom UI is
then a matter of adding one entry here, not a new app's worth of
boilerplate.

CompanyInfo and DocumentSettings are deliberately NOT in this registry --
they're singletons with their own dedicated edit-only views (no list/
create/delete), since "add a new Company Info row" or "delete the Document
Settings row" isn't a meaningful action.
"""

from .models import Client, Commodity, Currency, Item, PaymentTerm, Port, ReferenceDocument, Supplier, Transporter

MASTER_REGISTRY = {
    "clients": {
        "model": Client,
        "verbose_name": "Client",
        "verbose_name_plural": "Clients",
        "fields": ["company_name", "contact_person", "email", "phone", "address",
                   "billing_address", "shipping_address", "tax_number",
                   "currency", "payment_terms", "sales_representative", "is_active"],
        "list_columns": ["company_name", "customer_code", "contact_person", "phone", "currency", "is_active"],
        "search_fields": ["company_name", "customer_code", "contact_person", "email"],
        "ordering": ["company_name"],
    },
    "suppliers": {
        "model": Supplier,
        "verbose_name": "Supplier",
        "verbose_name_plural": "Suppliers",
        "fields": ["company_name", "contact_person", "email", "phone", "address",
                   "tax_number", "currency", "payment_terms", "supplier_type", "is_active"],
        "list_columns": ["company_name", "supplier_type", "contact_person", "phone", "currency", "is_active"],
        "search_fields": ["company_name", "contact_person", "email", "tax_number"],
        "ordering": ["company_name"],
    },
    "currencies": {
        "model": Currency,
        "verbose_name": "Currency",
        "verbose_name_plural": "Currencies",
        "fields": ["name", "code", "symbol", "exchange_rate", "is_active"],
        "list_columns": ["code", "name", "symbol", "exchange_rate", "is_active"],
        "search_fields": ["name", "code"],
        "ordering": ["code"],
    },
    "payment-terms": {
        "model": PaymentTerm,
        "verbose_name": "Payment Term",
        "verbose_name_plural": "Payment Terms",
        "fields": ["name", "days", "description", "is_active"],
        "list_columns": ["name", "days", "is_active"],
        "search_fields": ["name"],
        "ordering": ["days"],
    },
    "commodities": {
        "model": Commodity,
        "verbose_name": "Commodity",
        "verbose_name_plural": "Commodities",
        "fields": ["name", "description", "hs_code", "is_active"],
        "list_columns": ["name", "hs_code", "is_active"],
        "search_fields": ["name", "hs_code"],
        "ordering": ["name"],
    },
    "items": {
        "model": Item,
        "verbose_name": "Item",
        "verbose_name_plural": "Items",
        "fields": ["code", "name", "description", "item_type", "supplier", "currency", "cost_price", "selling_price",
                   "vat_applicable", "vat_percentage", "is_active"],
        "list_columns": ["code", "name", "item_type", "supplier", "cost_price", "selling_price", "is_active"],
        "search_fields": ["code", "name"],
        "ordering": ["item_type", "name"],
    },
    "ports": {
        "model": Port,
        "verbose_name": "Port",
        "verbose_name_plural": "Ports",
        "fields": ["name", "code", "country", "port_type", "is_active"],
        "list_columns": ["name", "code", "country", "port_type", "is_active"],
        "search_fields": ["name", "code", "country"],
        "ordering": ["country", "name"],
    },
    "transporters": {
        "model": Transporter,
        "verbose_name": "Transporter",
        "verbose_name_plural": "Transporters",
        "fields": ["company_name", "contact_person", "phone", "email", "vehicle_types",
                   "license_number", "license_expiry", "is_active"],
        "list_columns": ["company_name", "contact_person", "phone", "license_number", "is_active"],
        "search_fields": ["company_name", "contact_person", "license_number"],
        "ordering": ["company_name"],
    },
    "reference-documents": {
        "model": ReferenceDocument,
        "verbose_name": "Reference Document",
        "verbose_name_plural": "Reference Documents",
        "fields": ["name", "file", "description", "is_active"],
        "list_columns": ["name", "file", "created_at", "is_active"],
        "search_fields": ["name", "description"],
        "ordering": ["-created_at"],
        "has_usage_view": True,
    },
}


def get_entry_or_404(slug):
    from django.http import Http404
    entry = MASTER_REGISTRY.get(slug)
    if not entry:
        raise Http404(f"Unknown master data type: {slug}")
    return entry
