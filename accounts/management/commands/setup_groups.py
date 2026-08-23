"""
Idempotently create the ERP's Django Groups and assign them the appropriate
model permissions.

Run after every `migrate` (including in later phases, once quotations/
proforma/invoicing/expenses models exist) so newly added permissions get
attached to the right roles:

    python manage.py migrate
    python manage.py setup_groups

Design: permission assignment is expressed as "app_label.codename" strings
per role. Codenames that don't exist yet (because that app's models haven't
been built in an earlier phase) are skipped with a warning instead of
raising, so this command is safe to run in every phase from Phase 1 onward
and will simply grant more as the schema grows.
"""

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

from core.permissions import ALL_ROLES, ADMINISTRATOR, SALES_MANAGER, \
    SALES_REPRESENTATIVE, OPERATIONS_OFFICER, FINANCE_OFFICER, ACCOUNTANT, \
    MANAGEMENT_VIEWER

# Role -> list of "app_label.codename" permission strings.
# Administrator gets everything (handled separately below, not listed here).
ROLE_PERMISSIONS = {
    SALES_MANAGER: [
        "quotations.add_quotation", "quotations.change_quotation",
        "quotations.view_quotation", "quotations.delete_quotation",
        "quotations.approve_quotation",
        "proforma.add_proformainvoice", "proforma.change_proformainvoice",
        "proforma.view_proformainvoice", "proforma.approve_proformainvoice",
        "masters.add_client", "masters.change_client", "masters.view_client",
        "masters.view_item", "masters.view_commodity",
    ],
    SALES_REPRESENTATIVE: [
        "quotations.add_quotation", "quotations.change_quotation",
        "quotations.view_quotation",
        "masters.view_client", "masters.view_item", "masters.view_commodity",
    ],
    OPERATIONS_OFFICER: [
        "proforma.view_proformainvoice", "proforma.change_proformainvoice",
        "masters.view_transporter", "masters.change_transporter",
        "masters.view_port",
    ],
    FINANCE_OFFICER: [
        "invoicing.add_invoice", "invoicing.change_invoice", "invoicing.view_invoice",
        "invoicing.add_payment", "invoicing.change_payment", "invoicing.view_payment",
        "invoicing.add_receipt", "invoicing.view_receipt",
        "accounting.view_statementofaccount", "accounting.add_statementofaccount",
        "expenses.add_supplierpayment", "expenses.view_supplierpayment",
    ],
    ACCOUNTANT: [
        "accounting.view_statementofaccount", "accounting.add_statementofaccount",
        "accounting.add_ledgerentry", "accounting.view_ledgerentry",
        "expenses.add_expense", "expenses.change_expense", "expenses.view_expense",
        "expenses.approve_expense",
    ],
    MANAGEMENT_VIEWER: [
        "quotations.view_quotation",
        "proforma.view_proformainvoice",
        "invoicing.view_invoice", "invoicing.view_payment", "invoicing.view_receipt",
        "expenses.view_expense",
        "accounting.view_statementofaccount",
    ],
}


class Command(BaseCommand):
    help = "Create/update the ERP's Django Groups and their permissions."

    def handle(self, *args, **options):
        groups = {}
        for role_name in ALL_ROLES:
            group, created = Group.objects.get_or_create(name=role_name)
            groups[role_name] = group
            self.stdout.write(
                self.style.SUCCESS(f"{'Created' if created else 'Found'} group: {role_name}")
            )

        # Administrator: full access to everything currently registered.
        admin_group = groups[ADMINISTRATOR]
        all_perms = Permission.objects.all()
        admin_group.permissions.set(all_perms)
        self.stdout.write(self.style.SUCCESS(
            f"Administrator granted all {all_perms.count()} current permissions."
        ))

        for role_name, perm_strings in ROLE_PERMISSIONS.items():
            group = groups[role_name]
            resolved = []
            for perm_string in perm_strings:
                app_label, codename = perm_string.split(".")
                try:
                    resolved.append(
                        Permission.objects.get(content_type__app_label=app_label, codename=codename)
                    )
                except Permission.DoesNotExist:
                    self.stdout.write(self.style.WARNING(
                        f"  Skipping {perm_string} (not registered yet - add it once that app/model exists)"
                    ))
            group.permissions.set(resolved)
            self.stdout.write(self.style.SUCCESS(
                f"{role_name}: {len(resolved)} permissions assigned."
            ))

        self.stdout.write(self.style.SUCCESS("Group/permission setup complete."))
