from django.contrib import admin

from .models import (
    Client, CompanyInfo, Commodity, Currency, DocumentSettings, Item,
    PaymentTerm, Port, ReferenceDocument, Supplier, Transporter,
)


@admin.register(Currency)
class CurrencyAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "symbol", "exchange_rate", "is_active")
    list_editable = ("exchange_rate", "is_active")
    search_fields = ("code", "name")
    list_filter = ("is_active",)


@admin.register(PaymentTerm)
class PaymentTermAdmin(admin.ModelAdmin):
    list_display = ("name", "days", "is_active")
    list_editable = ("is_active",)
    search_fields = ("name",)


@admin.register(Commodity)
class CommodityAdmin(admin.ModelAdmin):
    list_display = ("name", "hs_code", "is_active")
    search_fields = ("name", "hs_code")
    list_filter = ("is_active",)


@admin.register(Port)
class PortAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "country", "port_type", "is_active")
    list_filter = ("port_type", "country", "is_active")
    search_fields = ("name", "code", "country")


@admin.register(Transporter)
class TransporterAdmin(admin.ModelAdmin):
    list_display = ("company_name", "contact_person", "phone", "license_number", "license_expiry", "is_active")
    search_fields = ("company_name", "contact_person", "license_number")
    list_filter = ("is_active",)


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("company_name", "supplier_type", "contact_person", "phone", "currency", "payment_terms", "is_active")
    list_filter = ("supplier_type", "currency", "is_active")
    search_fields = ("company_name", "contact_person", "email", "tax_number")
    autocomplete_fields = ("currency", "payment_terms")


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "item_type", "supplier", "currency", "cost_price", "selling_price",
                     "vat_applicable", "vat_percentage", "is_active")
    list_filter = ("item_type", "vat_applicable", "currency", "is_active")
    search_fields = ("code", "name")
    autocomplete_fields = ("supplier", "currency")
    list_editable = ("cost_price", "selling_price", "is_active")


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("company_name", "customer_code", "contact_person", "phone",
                     "currency", "payment_terms", "sales_representative", "is_active")
    list_filter = ("currency", "payment_terms", "sales_representative", "is_active")
    search_fields = ("company_name", "customer_code", "contact_person", "email", "tax_number")
    autocomplete_fields = ("currency", "payment_terms", "sales_representative")
    readonly_fields = ("customer_code",)
    fieldsets = (
        (None, {"fields": ("company_name", "customer_code", "is_active")}),
        ("Contact", {"fields": ("contact_person", "email", "phone")}),
        ("Addresses", {"fields": ("address", "billing_address", "shipping_address")}),
        ("Commercial Terms", {"fields": ("currency", "payment_terms", "sales_representative", "tax_number")}),
    )


@admin.register(ReferenceDocument)
class ReferenceDocumentAdmin(admin.ModelAdmin):
    list_display = ("name", "file", "created_at", "is_active")
    search_fields = ("name", "description")
    list_filter = ("is_active",)


@admin.register(CompanyInfo)
class CompanyInfoAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "email", "tax_id")

    def has_add_permission(self, request):
        # Singleton: block "Add" once a row exists.
        return not CompanyInfo.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DocumentSettings)
class DocumentSettingsAdmin(admin.ModelAdmin):
    list_display = ("quotation_prefix", "proforma_prefix", "invoice_prefix", "receipt_prefix", "default_vat_percentage")

    def has_add_permission(self, request):
        return not DocumentSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
