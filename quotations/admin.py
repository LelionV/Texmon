from django.contrib import admin

from .models import Quotation, QuotationItem


class QuotationItemInline(admin.TabularInline):
    model = QuotationItem
    extra = 1
    autocomplete_fields = ("item",)
    fields = ("item", "description", "quantity", "unit_price", "vat_percentage")


@admin.register(Quotation)
class QuotationAdmin(admin.ModelAdmin):
    list_display = (
        "quotation_number", "client", "date", "status", "currency",
        "grand_total", "sales_representative",
    )
    list_filter = ("status", "currency", "sales_representative")
    search_fields = ("quotation_number", "client__company_name", "reference_document__name")
    autocomplete_fields = ("client", "currency", "payment_terms", "sales_representative",
                            "origin_port", "destination_port", "reference_document")
    readonly_fields = ("quotation_number", "subtotal", "vat_total", "grand_total",
                        "submitted_at", "approved_at", "approved_by")
    inlines = [QuotationItemInline]
    date_hierarchy = "date"

    fieldsets = (
        (None, {"fields": ("quotation_number", "client", "date", "valid_until", "status")}),
        ("Commercial Terms", {"fields": ("currency", "payment_terms", "sales_representative")}),
        ("Shipment", {"fields": ("origin_port", "destination_port", "final_destination",
                                  "commodity", "commodity_quantity", "commodity_unit")}),
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
