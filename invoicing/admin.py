from django.contrib import admin

from .models import Invoice, InvoiceItem, Payment, Receipt


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 0
    autocomplete_fields = ("item",)
    fields = ("item", "description", "quantity", "unit_price", "vat_percentage")


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fields = ("payment_date", "amount", "payment_method", "reference_number", "bank_account")
    readonly_fields = ()


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_number", "proforma_invoice", "client", "date", "due_date",
                     "status", "grand_total", "paid_amount", "balance_due")
    list_filter = ("status", "currency")
    search_fields = ("invoice_number", "proforma_invoice__pi_number", "client__company_name")
    autocomplete_fields = ("proforma_invoice", "client", "currency", "payment_terms",
                            "sales_representative", "origin_port", "destination_port")
    readonly_fields = ("invoice_number", "subtotal", "vat_total", "grand_total",
                        "paid_amount", "balance_due", "status")
    inlines = [InvoiceItemInline, PaymentInline]
    date_hierarchy = "date"


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("invoice", "payment_date", "amount", "payment_method", "reference_number", "created_by")
    list_filter = ("payment_method", "payment_date")
    search_fields = ("invoice__invoice_number", "reference_number")
    autocomplete_fields = ("invoice",)
    date_hierarchy = "payment_date"


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ("receipt_number", "invoice", "amount", "date")
    search_fields = ("receipt_number", "invoice__invoice_number")
    date_hierarchy = "date"

    def has_add_permission(self, request):
        return False  # Receipts are only ever created automatically from a Payment.

    def has_change_permission(self, request, obj=None):
        return False
