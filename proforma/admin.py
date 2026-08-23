from django.contrib import admin

from .models import ProformaInvoice, ProformaInvoiceItem


class ProformaInvoiceItemInline(admin.TabularInline):
    model = ProformaInvoiceItem
    extra = 0
    autocomplete_fields = ("item",)
    fields = ("item", "description", "quantity", "unit_price", "vat_percentage")


@admin.register(ProformaInvoice)
class ProformaInvoiceAdmin(admin.ModelAdmin):
    list_display = ("pi_number", "quotation", "client", "date", "status",
                     "bl_number", "vessel", "grand_total")
    list_filter = ("status", "currency")
    search_fields = ("pi_number", "quotation__quotation_number", "client__company_name",
                      "bl_number", "container_number", "vessel")
    autocomplete_fields = ("quotation", "client", "currency", "payment_terms",
                            "sales_representative", "origin_port", "destination_port", "reference_document")
    readonly_fields = ("pi_number", "subtotal", "vat_total", "grand_total",
                        "submitted_at", "approved_at", "approved_by")
    inlines = [ProformaInvoiceItemInline]
    date_hierarchy = "date"

    fieldsets = (
        (None, {"fields": ("pi_number", "quotation", "client", "date", "status")}),
        ("Commercial Terms", {"fields": ("currency", "payment_terms", "sales_representative")}),
        ("Shipment", {"fields": ("origin_port", "destination_port", "final_destination",
                                  "commodity", "commodity_quantity", "commodity_unit")}),
        ("Shipping Details", {"fields": ("bl_number", "shipment_reference", "container_number",
                                          "vessel", "eta", "etd")}),
        ("Other", {"fields": ("reference_document", "notes", "terms")}),
        ("Totals", {"fields": ("subtotal", "vat_total", "grand_total")}),
        ("Workflow", {"fields": ("submitted_at", "approved_at", "approved_by")}),
    )

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for obj in instances:
            obj.save()
        for obj in formset.deleted_objects:
            obj.delete()
        formset.save_m2m()
        form.instance.recalculate_totals()
