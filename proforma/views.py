"""
Proforma Invoice views.

Same visibility rule as quotations: a plain Sales Representative only sees
their own PIs (sales_representative == request.user, copied from the
quotation at conversion time); broader roles see everything.

Creation is intentionally NOT a generic CreateView -- there is no "new blank
PI" form. The only entry point is `create_from_quotation`, a POST-only view
reached from an Approved quotation's detail page, which delegates straight
to `ProformaInvoice.create_from_quotation()`.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView, UpdateView

from accounts.models import UserActivityLog
from quotations.models import Quotation
from .forms import ProformaInvoiceForm, ProformaInvoiceItemFormSet
from .models import ProformaInvoice
from core.pdf import render_pdf_template

BROAD_VISIBILITY_GROUPS = {
    "Administrator", "Sales Manager", "Finance Officer", "Accountant", "Management Viewer",
}


class ProformaQuerysetMixin:
    def get_queryset(self):
        qs = ProformaInvoice.objects.select_related(
            "client", "currency", "payment_terms", "sales_representative", "quotation"
        )
        user = self.request.user
        if user.is_superuser or user.is_staff or BROAD_VISIBILITY_GROUPS & set(user.role_names):
            return qs
        return qs.filter(sales_representative=user)


class ProformaListView(LoginRequiredMixin, ProformaQuerysetMixin, ListView):
    model = ProformaInvoice
    template_name = "proforma/proforma_list.html"
    context_object_name = "proformas"
    paginate_by = 25

    def get_queryset(self):
        qs = super().get_queryset().order_by("-date", "-id")
        status = self.request.GET.get("status")
        q = self.request.GET.get("q")
        if status:
            qs = qs.filter(status=status)
        if q:
            qs = qs.filter(pi_number__icontains=q) | qs.filter(client__company_name__icontains=q)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = ProformaInvoice.Status.choices
        ctx["current_status"] = self.request.GET.get("status", "")
        ctx["q"] = self.request.GET.get("q", "")
        return ctx


class ProformaDetailView(LoginRequiredMixin, ProformaQuerysetMixin, DetailView):
    model = ProformaInvoice
    template_name = "proforma/proforma_detail.html"
    context_object_name = "proforma"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["items"] = self.object.items.select_related("item")
        return ctx


class ProformaUpdateView(LoginRequiredMixin, PermissionRequiredMixin, ProformaQuerysetMixin, UpdateView):
    model = ProformaInvoice
    form_class = ProformaInvoiceForm
    template_name = "proforma/proforma_form.html"
    permission_required = "proforma.change_proformainvoice"

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        if not self.object.is_editable:
            messages.error(request, f"{self.object.pi_number} is {self.object.get_status_display()} and can no longer be edited.")
            return redirect(self.object.get_absolute_url())
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.POST:
            ctx["formset"] = ProformaInvoiceItemFormSet(self.request.POST, instance=self.object)
        else:
            ctx["formset"] = ProformaInvoiceItemFormSet(instance=self.object)
        return ctx

    def form_valid(self, form):
        form.instance.updated_by = self.request.user
        context = self.get_context_data()
        formset = context["formset"]
        if formset.is_valid():
            self.object = form.save()
            formset.instance = self.object
            formset.save()
            self.object.recalculate_totals()
            UserActivityLog.log(self.request.user, UserActivityLog.Action.UPDATE,
                                 f"Updated proforma invoice {self.object.pi_number}",
                                 obj=self.object, request=self.request)
            messages.success(self.request, f"{self.object.pi_number} updated.")
            return redirect(self.object.get_absolute_url())
        return self.render_to_response(self.get_context_data(form=form))


# -- creation from an approved quotation -------------------------------------

@login_required
@permission_required("proforma.add_proformainvoice", raise_exception=True)
@require_POST
def create_from_quotation(request, quotation_pk):
    quotation = get_object_or_404(Quotation, pk=quotation_pk)
    try:
        pi = ProformaInvoice.create_from_quotation(quotation, user=request.user)
        UserActivityLog.log(request.user, UserActivityLog.Action.CONVERT,
                             f"Converted {quotation.quotation_number} to {pi.pi_number}",
                             obj=pi, request=request)
        messages.success(request, f"{quotation.quotation_number} converted to {pi.pi_number}.")
        return redirect(pi.get_absolute_url())
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages) if hasattr(e, "messages") else str(e))
        return redirect(quotation.get_absolute_url())


# -- workflow transitions -----------------------------------------------------

def _transition(request, pk, action, log_action, success_msg):
    pi = get_object_or_404(ProformaInvoice, pk=pk)
    try:
        getattr(pi, action)(user=request.user)
        UserActivityLog.log(request.user, log_action, success_msg.format(pi), obj=pi, request=request)
        messages.success(request, success_msg.format(pi))
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages) if hasattr(e, "messages") else str(e))
    return redirect(pi.get_absolute_url())


@login_required
@permission_required("proforma.submit_proformainvoice", raise_exception=True)
def submit_proforma(request, pk):
    return _transition(request, pk, "submit", UserActivityLog.Action.SUBMIT, "{} submitted for approval.")


@login_required
@permission_required("proforma.approve_proformainvoice", raise_exception=True)
def approve_proforma(request, pk):
    return _transition(request, pk, "approve", UserActivityLog.Action.APPROVE, "{} approved.")


@login_required
@permission_required("proforma.approve_proformainvoice", raise_exception=True)
def reject_proforma(request, pk):
    return _transition(request, pk, "reject", UserActivityLog.Action.REJECT, "{} rejected.")


@login_required
@permission_required("proforma.change_proformainvoice", raise_exception=True)
def revert_proforma(request, pk):
    return _transition(request, pk, "revert_to_draft", UserActivityLog.Action.UPDATE, "{} reverted to Draft.")


# -- PDF -----------------------------------------------------------------------

def _proforma_status_banner(pi):
    if pi.status == pi.Status.DRAFT:
        return {"text": "DRAFT — NOT YET SUBMITTED FOR APPROVAL", "level": "warning"}
    if pi.status == pi.Status.SUBMITTED:
        return {"text": "PENDING APPROVAL", "level": "warning"}
    if pi.status == pi.Status.REJECTED:
        return {"text": "REJECTED", "level": "danger"}
    return None

@login_required
def proforma_pdf(request, pk):
    pi = get_object_or_404(ProformaInvoice, pk=pk)

    from masters.models import CompanyInfo
    from core.pdf import render_pdf_template

    company_info = CompanyInfo.get_solo()

    context = {
        "proforma": pi,

        "items": pi.items.select_related("item"),

        "company_info": company_info,

        "document_number": pi.pi_number,

        "reference_number": (
            pi.reference_document.name
            if pi.reference_document_id
            else ""
        ),

        "document_date": pi.date,

        "customer": pi.client,

        "subtotal": pi.subtotal,
        "vat_total": pi.vat_total,
        "grand_total": pi.grand_total,

        "currency_symbol": pi.currency.symbol,
        "currency_code": pi.currency.code,

        "doc_tag": (
            pi.get_shipment_type_display()
            if pi.shipment_type
            else None
        ),

        "status_banner": _proforma_status_banner(pi),

        "prepared_by": pi.created_by,
        "approved_by": pi.approved_by,
    }

    # Shared PDF renderer automatically adds:
    # - company_info
    # - logo_base64
    pdf_bytes = render_pdf_template(
        request,
        "proforma/proforma_pdf.html",
        context,
    )

    UserActivityLog.log(
        request.user,
        UserActivityLog.Action.PRINT,
        f"Downloaded PDF for {pi.pi_number}",
        obj=pi,
        request=request,
    )

    response = HttpResponse(
        pdf_bytes,
        content_type="application/pdf",
    )

    response["Content-Disposition"] = (
        f'inline; filename="{pi.pi_number}.pdf"'
    )

    return response