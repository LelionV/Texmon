"""
Idempotently seeds the default expense categories named in the spec:

    Operations: Transport, Fuel, Warehouse, Customs
    Administration: Rent, Utilities, Salaries

Run with: python manage.py setup_expense_categories
Safe to re-run; existing categories are left untouched (get_or_create).
"""

from django.core.management.base import BaseCommand

from expenses.models import ExpenseCategory

DEFAULT_CATEGORIES = {
    ExpenseCategory.CategoryType.OPERATIONS: ["Transport", "Fuel", "Warehouse", "Customs"],
    ExpenseCategory.CategoryType.ADMINISTRATION: ["Rent", "Utilities", "Salaries"],
}


class Command(BaseCommand):
    help = "Create the default Operations/Administration expense categories."

    def handle(self, *args, **options):
        created_count = 0
        for category_type, names in DEFAULT_CATEGORIES.items():
            for name in names:
                _, created = ExpenseCategory.objects.get_or_create(
                    name=name, category_type=category_type,
                )
                if created:
                    created_count += 1
                    self.stdout.write(self.style.SUCCESS(f"Created: {name} ({category_type})"))
        self.stdout.write(self.style.SUCCESS(f"Done. {created_count} new categories created."))
