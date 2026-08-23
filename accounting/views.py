"""
Accounting views: the client ledger and Statement of Account generation/PDF.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import DetailView, FormView, ListView

from .forms import GenerateStatementForm
from .models import LedgerEntry, StatementOfAccount


class StatementListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = StatementOfAccount
    template_name = "accounting/statement_list.html"
    context_object_name = "statements"
    paginate_by = 25
    permission_required = "accounting.view_statementofaccount"

    def get_queryset(self):
        return StatementOfAccount.objects.select_related("client").order_by("-date_to", "-id")


class GenerateStatementView(LoginRequiredMixin, PermissionRequiredMixin, FormView):
    form_class = GenerateStatementForm
    template_name = "accounting/statement_generate.html"
    permission_required = "accounting.add_statementofaccount"

    def form_valid(self, form):
        statement = StatementOfAccount.generate(
            client=form.cleaned_data["client"],
            date_from=form.cleaned_data["date_from"],
            date_to=form.cleaned_data["date_to"],
            user=self.request.user,
        )
        messages.success(self.request, f"{statement.statement_number} generated for {statement.client.company_name}.")
        return redirect(statement.get_absolute_url())


class StatementDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = StatementOfAccount
    template_name = "accounting/statement_detail.html"
    context_object_name = "statement"
    permission_required = "accounting.view_statementofaccount"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["lines"] = self.object.get_lines()
        return ctx


@login_required
@permission_required("accounting.view_statementofaccount", raise_exception=True)
def statement_pdf(request, pk):
    statement = get_object_or_404(StatementOfAccount, pk=pk)
    from masters.models import CompanyInfo
    from core.pdf import render_pdf

    html_string = render(request, "accounting/statement_pdf.html", {
        "statement": statement,
        "lines": statement.get_lines(),
        "company_info": CompanyInfo.get_solo(),
        "document_number": statement.statement_number,
        "document_date": statement.date_to,
        "customer": statement.client,
    }).content.decode("utf-8")

    pdf_bytes = render_pdf(html_string)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{statement.statement_number}.pdf"'
    return response


class ClientLedgerView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """Full running ledger for one client -- Accountant/Finance view, not a
    Statement of Account (no period/opening-closing snapshot), just the
    live entry-by-entry history."""
    model = LedgerEntry
    template_name = "accounting/client_ledger.html"
    context_object_name = "entries"
    permission_required = "accounting.view_ledgerentry"
    paginate_by = 50

    def get_queryset(self):
        from masters.models import Client
        self.client_obj = get_object_or_404(Client, pk=self.kwargs["client_pk"])
        return LedgerEntry.objects.filter(client=self.client_obj).order_by("date", "id")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["client_obj"] = self.client_obj
        return ctx
