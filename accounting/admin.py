from django.contrib import admin

from .models import LedgerEntry, StatementOfAccount


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ("client", "date", "entry_type", "reference_number", "debit", "credit", "running_balance")
    list_filter = ("entry_type", "date")
    search_fields = ("client__company_name", "reference_number")
    date_hierarchy = "date"
    readonly_fields = [f.name for f in LedgerEntry._meta.fields]

    def has_add_permission(self, request):
        return False  # Ledger entries are only ever posted automatically.

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StatementOfAccount)
class StatementOfAccountAdmin(admin.ModelAdmin):
    list_display = ("statement_number", "client", "date_from", "date_to", "opening_balance", "closing_balance")
    list_filter = ("client",)
    search_fields = ("statement_number", "client__company_name")
    readonly_fields = ("statement_number", "opening_balance", "closing_balance")
    date_hierarchy = "date_to"
