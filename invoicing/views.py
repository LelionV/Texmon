"""
Invoice / Payment / Receipt views.

Visibility mirrors quotations/proforma: Sales Reps see only their own
invoices; Finance Officer/Accountant/Administrator/Sales Manager/Management
Viewer see everything (Finance-facing roles need full visibility to do their
jobs, unlike the sales-rep "own clients" restriction).
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView

from accounts.models import UserActivityLog
from proforma.models import ProformaInvoice
from .forms import PaymentForm
from .models import Invoice, Payment, Receipt

BROAD_VISIBILITY_GROUPS = {
    "Administrator", "Sales Manager", "Finance Officer", "Accountant", "Management Viewer",
}


class InvoiceQuerysetMixin:
    def get_queryset(self):
        qs = Invoice.objects.select_related("client", "currency", "payment_terms", "sales_representative", "proforma_invoice")
        user = self.request.user
        if user.is_superuser or user.is_staff or BROAD_VISIBILITY_GROUPS & set(user.role_names):
            return qs
        return qs.filter(sales_representative=user)


class InvoiceListView(LoginRequiredMixin, InvoiceQuerysetMixin, ListView):
    model = Invoice
    template_name = "invoicing/invoice_list.html"
    context_object_name = "invoices"
    paginate_by = 25

    def get_queryset(self):
        qs = super().get_queryset().order_by("-date", "-id")
        status = self.request.GET.get("status")
        q = self.request.GET.get("q")
        if status:
            qs = qs.filter(status=status)
        if q:
            qs = qs.filter(invoice_number__icontains=q) | qs.filter(client__company_name__icontains=q)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = Invoice.Status.choices
        ctx["current_status"] = self.request.GET.get("status", "")
        ctx["q"] = self.request.GET.get("q", "")
        return ctx


class InvoiceDetailView(LoginRequiredMixin, InvoiceQuerysetMixin, DetailView):
    model = Invoice
    template_name = "invoicing/invoice_detail.html"
    context_object_name = "invoice"
    pk_url_kwarg = "pk"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["items"] = self.object.items.select_related("item")
        ctx["payments"] = self.object.payments.select_related("receipt")
        ctx["payment_form"] = PaymentForm(initial={"amount": self.object.balance_due})
        return ctx


@login_required
@permission_required("invoicing.add_invoice", raise_exception=True)
@require_POST
def create_from_proforma(request, proforma_pk):
    proforma = get_object_or_404(ProformaInvoice, pk=proforma_pk)
    try:
        invoice = Invoice.create_from_proforma(proforma, user=request.user)
        UserActivityLog.log(request.user, UserActivityLog.Action.CONVERT,
                             f"Converted {proforma.pi_number} to {invoice.invoice_number}",
                             obj=invoice, request=request)
        messages.success(request, f"{proforma.pi_number} converted to {invoice.invoice_number}.")
        return redirect(invoice.get_absolute_url())
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages) if hasattr(e, "messages") else str(e))
        return redirect(proforma.get_absolute_url())


def _invoice_status_banner(invoice):
    if invoice.status == invoice.Status.PAID:
        return {"text": "PAID IN FULL", "level": "success"}
    if invoice.status == invoice.Status.PARTIALLY_PAID:
        return {"text": f"PARTIALLY PAID — BALANCE DUE: {invoice.currency.symbol}{invoice.balance_due:,.2f}", "level": "info"}
    if invoice.status == invoice.Status.CANCELLED:
        return {"text": "CANCELLED", "level": "danger"}
    return {"text": f"BALANCE DUE: {invoice.currency.symbol}{invoice.balance_due:,.2f}", "level": "info"}

@login_required
def invoice_pdf(request, pk):
    invoice = get_object_or_404(Invoice, pk=pk)

    from masters.models import CompanyInfo
    from core.pdf import render_pdf_template

    context = {
        "invoice": invoice,

        "items": invoice.items.select_related("item"),

        "company_info": CompanyInfo.get_solo(),

        "document_number": invoice.invoice_number,

        "reference_number": (
            invoice.reference_document.name
            if invoice.reference_document_id
            else ""
        ),

        "document_date": invoice.date,

        "customer": invoice.client,

        "subtotal": invoice.subtotal,
        "vat_total": invoice.vat_total,
        "grand_total": invoice.grand_total,

        "currency_symbol": invoice.currency.symbol,
        "currency_code": invoice.currency.code,

        "doc_tag": (
            invoice.get_shipment_type_display()
            if invoice.shipment_type
            else None
        ),

        "status_banner": _invoice_status_banner(invoice),

        "prepared_by": invoice.created_by,
    }

    # Shared PDF renderer automatically provides:
    # - company_info
    # - logo_base64
    pdf_bytes = render_pdf_template(
        request,
        "invoicing/invoice_pdf.html",
        context,
    )

    UserActivityLog.log(
        request.user,
        UserActivityLog.Action.PRINT,
        f"Downloaded PDF for {invoice.invoice_number}",
        obj=invoice,
        request=request,
    )

    response = HttpResponse(
        pdf_bytes,
        content_type="application/pdf",
    )

    response["Content-Disposition"] = (
        f'inline; filename="{invoice.invoice_number}.pdf"'
    )

    return response
# -- payments -----------------------------------------------------------------

@login_required
@permission_required("invoicing.add_payment", raise_exception=True)
@require_POST
def add_payment(request, invoice_pk):
    invoice = get_object_or_404(Invoice, pk=invoice_pk)
    form = PaymentForm(request.POST)
    if form.is_valid():
        payment = form.save(commit=False)
        payment.invoice = invoice
        payment.created_by = request.user
        payment.updated_by = request.user
        try:
            payment.save()
            UserActivityLog.log(request.user, UserActivityLog.Action.PAYMENT,
                                 f"Recorded payment of {payment.amount} on {invoice.invoice_number}",
                                 obj=invoice, request=request)
            messages.success(request, f"Payment of {invoice.currency.symbol}{payment.amount} recorded.")
        except ValidationError as e:
            messages.error(request, "; ".join(e.messages) if hasattr(e, "messages") else str(e))
    else:
        for field, errors in form.errors.items():
            for err in errors:
                messages.error(request, f"{field}: {err}")
    return redirect(invoice.get_absolute_url())


class PaymentListView(LoginRequiredMixin, ListView):
    model = Payment
    template_name = "invoicing/payment_list.html"
    context_object_name = "payments"
    paginate_by = 25

    def get_queryset(self):
        qs = Payment.objects.select_related("invoice", "invoice__client")
        user = self.request.user
        if not (user.is_superuser or user.is_staff or BROAD_VISIBILITY_GROUPS & set(user.role_names)):
            qs = qs.filter(invoice__sales_representative=user)
        return qs.order_by("-payment_date", "-id")


# -- receipts -------------------------------------------------------------

class ReceiptListView(LoginRequiredMixin, ListView):
    model = Receipt
    template_name = "invoicing/receipt_list.html"
    context_object_name = "receipts"
    paginate_by = 25

    def get_queryset(self):
        qs = Receipt.objects.select_related("invoice", "invoice__client", "payment")
        user = self.request.user
        if not (user.is_superuser or user.is_staff or BROAD_VISIBILITY_GROUPS & set(user.role_names)):
            qs = qs.filter(invoice__sales_representative=user)
        return qs.order_by("-date", "-id")


class ReceiptDetailView(LoginRequiredMixin, DetailView):
    model = Receipt
    template_name = "invoicing/receipt_detail.html"
    context_object_name = "receipt"

@login_required
def receipt_pdf(request, pk):
    receipt = get_object_or_404(Receipt, pk=pk)

    from masters.models import CompanyInfo
    from core.pdf import render_pdf_template

    context = {
        "receipt": receipt,

        "invoice": receipt.invoice,

        "company_info": CompanyInfo.get_solo(),

        "document_number": receipt.receipt_number,

        "document_date": receipt.date,

        "customer": receipt.invoice.client,

        "currency_symbol": receipt.invoice.currency.symbol,

        "currency_code": receipt.invoice.currency.code,
    }

    # Shared PDF renderer automatically provides:
    # - company_info
    # - logo_base64
    pdf_bytes = render_pdf_template(
        request,
        "invoicing/receipt_pdf.html",
        context,
    )

    UserActivityLog.log(
        request.user,
        UserActivityLog.Action.PRINT,
        f"Downloaded PDF for {receipt.receipt_number}",
        obj=receipt,
        request=request,
    )

    response = HttpResponse(
        pdf_bytes,
        content_type="application/pdf",
    )

    response["Content-Disposition"] = (
        f'inline; filename="{receipt.receipt_number}.pdf"'
    )

    return response