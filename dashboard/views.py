"""
Role-aware dashboard. Rather than one fixed layout, `home()` decides which
KPI cards to show based on the user's Group membership (Administrator sees
everything; Sales/Finance/Operations see the slice relevant to their role,
per the spec's per-role dashboard breakdown). A user with no matching role
still gets a safe minimal view instead of an error.
"""

from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.shortcuts import render
from django.utils import timezone


def _sales_metrics(user, is_broad):
    from quotations.models import Quotation
    qs = Quotation.objects.all() if is_broad else Quotation.objects.filter(sales_representative=user)
    return {
        "my_quotations": qs.count(),
        "pending_approvals": qs.filter(status=Quotation.Status.SUBMITTED).count(),
        "converted_proformas": qs.filter(status=Quotation.Status.CONVERTED).count(),
        "draft_quotations": qs.filter(status=Quotation.Status.DRAFT).count(),
    }


def _finance_metrics():
    from invoicing.models import Invoice, Payment
    from accounting.models import StatementOfAccount
    thirty_days_ago = timezone.localdate() - timedelta(days=30)
    outstanding = Invoice.objects.exclude(status=Invoice.Status.PAID).aggregate(
        total=Sum("balance_due"))["total"] or 0
    payments_this_month = Payment.objects.filter(payment_date__gte=thirty_days_ago).aggregate(
        total=Sum("amount"))["total"] or 0
    return {
        "outstanding_invoices_total": outstanding,
        "outstanding_invoices_count": Invoice.objects.exclude(status=Invoice.Status.PAID).count(),
        "payments_this_month": payments_this_month,
        "statements_generated": StatementOfAccount.objects.count(),
    }


def _finance_supplier_metrics():
    from expenses.models import SupplierPayment
    thirty_days_ago = timezone.localdate() - timedelta(days=30)
    total = SupplierPayment.objects.filter(payment_date__gte=thirty_days_ago).aggregate(
        total=Sum("amount"))["total"] or 0
    return {"supplier_payments_this_month": total}


def _operations_metrics():
    from proforma.models import ProformaInvoice
    active = ProformaInvoice.objects.exclude(
        status__in=[ProformaInvoice.Status.CONVERTED, ProformaInvoice.Status.REJECTED],
    )
    from masters.models import Port, Transporter
    return {
        "active_shipments": active.count(),
        "bl_numbers": list(active.exclude(bl_number="").values_list("bl_number", "pi_number")[:8]),
        "ports_count": Port.objects.filter(is_active=True).count(),
        "transporters_count": Transporter.objects.filter(is_active=True).count(),
    }


def _admin_metrics():
    from invoicing.models import Invoice
    from expenses.models import Expense
    from masters.models import Client
    thirty_days_ago = timezone.localdate() - timedelta(days=30)
    total_sales = Invoice.objects.aggregate(total=Sum("grand_total"))["total"] or 0
    outstanding = Invoice.objects.exclude(status=Invoice.Status.PAID).aggregate(
        total=Sum("balance_due"))["total"] or 0
    payments_received = Invoice.objects.aggregate(total=Sum("paid_amount"))["total"] or 0
    total_expenses = Expense.objects.filter(status=Expense.Status.APPROVED).aggregate(
        total=Sum("amount"))["total"] or 0
    return {
        "total_sales": total_sales,
        "outstanding_invoices_total": outstanding,
        "payments_received": payments_received,
        "total_expenses": total_expenses,
        "profit_estimate": payments_received - total_expenses,
        "customers_count": Client.objects.filter(is_active=True).count(),
        "recent_invoices": Invoice.objects.order_by("-date")[:5],
    }


@login_required
def home(request):
    user = request.user
    roles = set(user.role_names) if hasattr(user, "role_names") else set()
    is_admin = user.is_superuser or "Administrator" in roles
    is_broad_sales_view = is_admin or "Sales Manager" in roles

    context = {"roles": list(roles), "is_admin": is_admin}

    if is_admin:
        context["admin_metrics"] = _admin_metrics()

    if is_admin or roles & {"Sales Manager", "Sales Representative"}:
        context["sales_metrics"] = _sales_metrics(user, is_broad_sales_view)

    if is_admin or roles & {"Finance Officer", "Accountant"}:
        context["finance_metrics"] = _finance_metrics()
        context["finance_metrics"].update(_finance_supplier_metrics())

    if is_admin or "Operations Officer" in roles:
        context["operations_metrics"] = _operations_metrics()

    # If nothing matched (e.g. Management Viewer, or a user with no group
    # yet), fall back to a minimal read-only summary rather than a blank page.
    if not any(k.endswith("_metrics") for k in context):
        context["viewer_metrics"] = _finance_metrics()

    return render(request, "dashboard/home.html", context)
