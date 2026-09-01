"""
Quotation views.

Visibility rule: per the spec ("Sales Representative: ... View own clients"),
a plain Sales Representative only sees quotations where they are the
assigned sales_representative. Anyone with broader visibility (Administrator,
Sales Manager, Finance Officer, Accountant, Management Viewer, or any
staff/superuser) sees everything. This is implemented once in
QuotationQuerysetMixin.get_queryset() rather than repeated per view.

Editing rule: only Draft quotations can have their header or line items
changed (Quotation.is_editable). QuotationEditableMixin.dispatch() enforces
this centrally for the update view.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from accounts.models import UserActivityLog
from core.pdf import get_logo_base64
from .forms import QuotationForm, QuotationItemFormSet
from .models import Quotation

BROAD_VISIBILITY_GROUPS = {
    "Administrator", "Sales Manager", "Finance Officer", "Accountant", "Management Viewer",
}


def commodity_suggestions():
    """Suggestion list for the free-text commodity field: existing master
    Commodity names (a starting point set of common goods) unioned with
    whatever free-text values have actually been typed on past quotations,
    so the list grows organically with real usage instead of being capped
    at whatever masters data was pre-loaded. Not enforced -- any text can
    still be entered, per the spec's "not limited to what is added"."""
    from masters.models import Commodity
    master_names = set(Commodity.objects.filter(is_active=True).values_list("name", flat=True))
    used_names = set(
        Quotation.objects.exclude(commodity="").values_list("commodity", flat=True).distinct()
    )
    return sorted(master_names | used_names)


class QuotationQuerysetMixin:
    def get_queryset(self):
        qs = Quotation.objects.select_related(
            "client", "currency", "payment_terms", "sales_representative"
        )
        user = self.request.user
        if user.is_superuser or user.is_staff or BROAD_VISIBILITY_GROUPS & set(user.role_names):
            return qs
        return qs.filter(sales_representative=user)


class QuotationEditableMixin:
    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        return response

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if not obj.is_editable:
            messages.error(self.request, f"{obj.quotation_number} is {obj.get_status_display()} and can no longer be edited.")
        return obj


class QuotationListView(LoginRequiredMixin, QuotationQuerysetMixin, ListView):
    model = Quotation
    template_name = "quotations/quotation_list.html"
    context_object_name = "quotations"
    paginate_by = 25

    def get_queryset(self):
        qs = super().get_queryset().order_by("-date", "-id")
        status = self.request.GET.get("status")
        q = self.request.GET.get("q")
        if status:
            qs = qs.filter(status=status)
        if q:
            qs = qs.filter(quotation_number__icontains=q) | qs.filter(client__company_name__icontains=q)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = Quotation.Status.choices
        ctx["current_status"] = self.request.GET.get("status", "")
        ctx["q"] = self.request.GET.get("q", "")
        return ctx


class QuotationDetailView(LoginRequiredMixin, QuotationQuerysetMixin, DetailView):
    model = Quotation
    template_name = "quotations/quotation_detail.html"
    context_object_name = "quotation"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["items"] = self.object.items.select_related("item")
        return ctx


class QuotationCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    model = Quotation
    form_class = QuotationForm
    template_name = "quotations/quotation_form.html"
    permission_required = "quotations.add_quotation"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.POST:
            ctx["formset"] = QuotationItemFormSet(self.request.POST, instance=self.object)
        else:
            ctx["formset"] = QuotationItemFormSet(instance=self.object)
        ctx["commodity_suggestions"] = commodity_suggestions()
        return ctx

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user
        form.instance.populate_from_client()
        context = self.get_context_data()
        formset = context["formset"]
        if formset.is_valid():
            self.object = form.save()
            formset.instance = self.object
            formset.save()
            self.object.recalculate_totals()
            UserActivityLog.log(self.request.user, UserActivityLog.Action.CREATE,
                                 f"Created quotation {self.object.quotation_number}",
                                 obj=self.object, request=self.request)
            messages.success(self.request, f"Quotation {self.object.quotation_number} created.")
            return redirect(self.object.get_absolute_url())
        return self.render_to_response(self.get_context_data(form=form))


class QuotationUpdateView(LoginRequiredMixin, PermissionRequiredMixin, QuotationEditableMixin, QuotationQuerysetMixin, UpdateView):
    model = Quotation
    form_class = QuotationForm
    template_name = "quotations/quotation_form.html"
    permission_required = "quotations.change_quotation"

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object() if kwargs.get("pk") else None
        if self.object and not self.object.is_editable:
            return redirect(self.object.get_absolute_url())
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.POST:
            ctx["formset"] = QuotationItemFormSet(self.request.POST, instance=self.object)
        else:
            ctx["formset"] = QuotationItemFormSet(instance=self.object)
        ctx["commodity_suggestions"] = commodity_suggestions()
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
                                 f"Updated quotation {self.object.quotation_number}",
                                 obj=self.object, request=self.request)
            messages.success(self.request, f"Quotation {self.object.quotation_number} updated.")
            return redirect(self.object.get_absolute_url())
        return self.render_to_response(self.get_context_data(form=form))


# -- workflow transitions --------------------------------------------------

def _transition(request, pk, action, log_action, success_msg):
    quotation = get_object_or_404(Quotation, pk=pk)
    try:
        getattr(quotation, action)(user=request.user)
        UserActivityLog.log(request.user, log_action, success_msg.format(quotation), obj=quotation, request=request)
        messages.success(request, success_msg.format(quotation))
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages) if hasattr(e, "messages") else str(e))
    return redirect(quotation.get_absolute_url())


@login_required
@permission_required("quotations.submit_quotation", raise_exception=True)
def submit_quotation(request, pk):
    return _transition(request, pk, "submit", UserActivityLog.Action.SUBMIT, "{} submitted for approval.")


@login_required
@permission_required("quotations.approve_quotation", raise_exception=True)
def approve_quotation(request, pk):
    return _transition(request, pk, "approve", UserActivityLog.Action.APPROVE, "{} approved.")


@login_required
@permission_required("quotations.approve_quotation", raise_exception=True)
def reject_quotation(request, pk):
    return _transition(request, pk, "reject", UserActivityLog.Action.REJECT, "{} rejected.")


@login_required
@permission_required("quotations.change_quotation", raise_exception=True)
def revert_quotation(request, pk):
    return _transition(request, pk, "revert_to_draft", UserActivityLog.Action.UPDATE, "{} reverted to Draft.")


# -- PDF --------------------------------------------------------------------

def _quotation_status_banner(quotation):
    if quotation.status == quotation.Status.DRAFT:
        return {"text": "DRAFT — NOT YET SUBMITTED FOR APPROVAL", "level": "warning"}
    if quotation.status == quotation.Status.SUBMITTED:
        return {"text": "PENDING APPROVAL", "level": "warning"}
    if quotation.status == quotation.Status.REJECTED:
        return {"text": "REJECTED", "level": "danger"}
    return None
@login_required
def quotation_pdf(request, pk):
    quotation = get_object_or_404(Quotation, pk=pk)

    from masters.models import CompanyInfo
    from core.pdf import render_pdf_template

    context = {
        "quotation": quotation,
        "items": quotation.items.select_related("item"),
        "company_info": CompanyInfo.get_solo(),

        "document_number": quotation.quotation_number,

        "reference_number": (
            quotation.reference_document.name
            if quotation.reference_document_id
            else ""
        ),

        "document_date": quotation.date,
        "customer": quotation.client,

        "subtotal": quotation.subtotal,
        "vat_total": quotation.vat_total,
        "grand_total": quotation.grand_total,

        "currency_symbol": quotation.currency.symbol,
        "currency_code": quotation.currency.code,

        "doc_tag": (
            quotation.get_shipment_type_display()
            if quotation.shipment_type
            else None
        ),

        "status_banner": _quotation_status_banner(quotation),

        "prepared_by": quotation.created_by,
        "approved_by": quotation.approved_by,
    }

    # Shared PDF renderer automatically provides:
    # - company_info
    # - logo_base64
    pdf_bytes = render_pdf_template(
        request,
        "quotations/quotation_pdf.html",
        context,
    )

    UserActivityLog.log(
        request.user,
        UserActivityLog.Action.PRINT,
        f"Downloaded PDF for {quotation.quotation_number}",
        obj=quotation,
        request=request,
    )

    response = HttpResponse(
        pdf_bytes,
        content_type="application/pdf",
    )

    response["Content-Disposition"] = (
        f'inline; filename="{quotation.quotation_number}.pdf"'
    )

    return response

# -- HTMX: dynamic empty formset row -----------------------------------------

@login_required
def quotation_item_empty_row(request):
    """Returns a single blank QuotationItem form row (rendered with the next
    formset index), used by the 'Add line' HTMX button on the create/edit
    template so JS doesn't need to hand-build form field names."""
    from django.template.loader import render_to_string
    from .forms import QuotationItemFormSet

    total_forms = int(request.GET.get("total_forms", 0))
    formset = QuotationItemFormSet()
    empty_form = formset.empty_form
    empty_form.prefix = formset.add_prefix(total_forms)
    html = render_to_string("quotations/_item_row.html", {"form": empty_form})
    return HttpResponse(html)
