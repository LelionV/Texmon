"""
Central registry of the Django Group names used for role-based access
control across the ERP, and the helper that (re)creates them.

Roles (per spec):
    Administrator
    Sales Manager
    Sales Representative
    Operations Officer
    Finance Officer
    Accountant
    Management Viewer

Group -> permission assignment is deliberately done in a management command
(accounts/management/commands/setup_groups.py) rather than a data migration,
because permissions objects only exist once every app's migrations
(including auto-created model permissions) have already run. Running it as
`python manage.py setup_groups` after `migrate` keeps this explicit and
re-runnable (idempotent) whenever new models/permissions are added in later
phases.
"""

ADMINISTRATOR = "Administrator"
SALES_MANAGER = "Sales Manager"
SALES_REPRESENTATIVE = "Sales Representative"
OPERATIONS_OFFICER = "Operations Officer"
FINANCE_OFFICER = "Finance Officer"
ACCOUNTANT = "Accountant"
MANAGEMENT_VIEWER = "Management Viewer"

ALL_ROLES = [
    ADMINISTRATOR,
    SALES_MANAGER,
    SALES_REPRESENTATIVE,
    OPERATIONS_OFFICER,
    FINANCE_OFFICER,
    ACCOUNTANT,
    MANAGEMENT_VIEWER,
]
