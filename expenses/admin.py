from django.contrib import admin

from .models import Expense, ExpenseCategory, SupplierPayment


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "category_type", "is_active")
    list_filter = ("category_type", "is_active")
    search_fields = ("name",)


class SupplierPaymentInline(admin.TabularInline):
    model = SupplierPayment
    extra = 0
    fields = ("supplier", "amount", "payment_date", "reference_number")
    autocomplete_fields = ("supplier",)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("expense_number", "category", "supplier", "date", "amount",
                     "vat_percentage", "total_amount", "status", "approved_by")
    list_filter = ("status", "category", "currency")
    search_fields = ("expense_number", "description", "supplier__company_name")
    autocomplete_fields = ("category", "supplier", "currency")
    readonly_fields = ("expense_number", "submitted_at", "approved_at", "approved_by")
    inlines = [SupplierPaymentInline]
    date_hierarchy = "date"


@admin.register(SupplierPayment)
class SupplierPaymentAdmin(admin.ModelAdmin):
    list_display = ("expense", "supplier", "amount", "payment_date", "reference_number")
    list_filter = ("payment_date",)
    search_fields = ("expense__expense_number", "supplier__company_name", "reference_number")
    autocomplete_fields = ("expense", "supplier")
    date_hierarchy = "payment_date"
