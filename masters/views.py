"""
Generic CRUD + history views driving the master-data custom UI (as opposed
to the Django admin, which remains available but is no longer the only way
to manage master data). One set of views serves every model listed in
masters/registry.py.

Delete uses Django's ProtectedError handling: most master models are
referenced by PROTECT foreign keys from transactional documents (a Client
can't be deleted while it has quotations, etc.), so a delete attempt that
would violate that is caught and turned into a friendly message instead of
a 500.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import CreateView, ListView, UpdateView, View

from .forms import build_master_form
from .registry import MASTER_REGISTRY, get_entry_or_404


class MasterSlugMixin:
    def dispatch(self, request, *args, **kwargs):
        self.slug = kwargs["slug"]
        self.entry = get_entry_or_404(self.slug)
        self.model = self.entry["model"]
        return super().dispatch(request, *args, **kwargs)

    def get_permission_required(self):
        opts = self.model._meta
        return (f"{opts.app_label}.{self.permission_action}_{opts.model_name}",)

    def common_context(self, **extra):
        return {
            "slug": self.slug,
            "entry": self.entry,
            "verbose_name": self.entry["verbose_name"],
            "verbose_name_plural": self.entry["verbose_name_plural"],
            **extra,
        }


class MasterHubView(LoginRequiredMixin, View):
    """Landing page listing every master-data type the user can manage."""
    def get(self, request):
        accessible = []
        for slug, entry in MASTER_REGISTRY.items():
            opts = entry["model"]._meta
            if request.user.has_perm(f"{opts.app_label}.view_{opts.model_name}"):
                accessible.append({"slug": slug, "entry": entry, "count": entry["model"].objects.count()})
        return render(request, "masters/master_hub.html", {"items": accessible})


class MasterListView(LoginRequiredMixin, MasterSlugMixin, PermissionRequiredMixin, ListView):
    template_name = "masters/master_list.html"
    context_object_name = "objects"
    paginate_by = 25
    permission_action = "view"

    def get_queryset(self):
        qs = self.model.objects.all()
        q = self.request.GET.get("q")
        if q and self.entry.get("search_fields"):
            query = Q()
            for f in self.entry["search_fields"]:
                query |= Q(**{f"{f}__icontains": q})
            qs = qs.filter(query)
        return qs.order_by(*self.entry.get("ordering", ["pk"]))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(self.common_context(
            columns=self.entry["list_columns"], q=self.request.GET.get("q", ""),
        ))
        return ctx


class MasterCreateView(LoginRequiredMixin, MasterSlugMixin, PermissionRequiredMixin, CreateView):
    template_name = "masters/master_form.html"
    permission_action = "add"

    def get_form_class(self):
        return build_master_form(self.entry)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(self.common_context(is_create=True))
        return ctx

    def form_valid(self, form):
        reason = form.cleaned_data.pop("change_reason", "")
        self.object = form.save(commit=False)
        if hasattr(self.object, "created_by_id"):
            self.object.created_by = self.request.user
            self.object.updated_by = self.request.user
        self.object._change_reason = reason
        self.object._history_user = self.request.user
        self.object.save()
        form.save_m2m()
        messages.success(self.request, f"{self.entry['verbose_name']} '{self.object}' created.")
        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse("masters:list", args=[self.slug])


class MasterUpdateView(LoginRequiredMixin, MasterSlugMixin, PermissionRequiredMixin, UpdateView):
    template_name = "masters/master_form.html"
    permission_action = "change"

    def get_queryset(self):
        return self.model.objects.all()

    def get_form_class(self):
        return build_master_form(self.entry)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(self.common_context(is_create=False))
        return ctx

    def form_valid(self, form):
        reason = form.cleaned_data.pop("change_reason", "")
        self.object = form.save(commit=False)
        if hasattr(self.object, "updated_by_id"):
            self.object.updated_by = self.request.user
        self.object._change_reason = reason
        self.object._history_user = self.request.user
        self.object.save()
        form.save_m2m()
        messages.success(self.request, f"{self.entry['verbose_name']} '{self.object}' updated.")
        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse("masters:list", args=[self.slug])


class MasterDeleteView(LoginRequiredMixin, MasterSlugMixin, PermissionRequiredMixin, View):
    permission_action = "delete"
    template_name = "masters/master_confirm_delete.html"

    def get_object(self):
        return get_object_or_404(self.model, pk=self.kwargs["pk"])

    def get(self, request, *args, **kwargs):
        obj = self.get_object()
        return render(request, self.template_name, self.common_context(object=obj))

    def post(self, request, *args, **kwargs):
        obj = self.get_object()
        reason = request.POST.get("change_reason", "")
        obj._change_reason = reason
        obj._history_user = request.user
        try:
            obj.delete()
            messages.success(request, f"{self.entry['verbose_name']} '{obj}' deleted.")
        except ProtectedError:
            messages.error(
                request,
                f"Cannot delete '{obj}' -- it is still referenced by other records "
                f"(quotations, invoices, etc.). Consider marking it inactive instead.",
            )
        return redirect(reverse("masters:list", args=[self.slug]))


class MasterHistoryView(LoginRequiredMixin, MasterSlugMixin, PermissionRequiredMixin, View):
    permission_action = "view"
    template_name = "masters/master_history.html"

    def get(self, request, *args, **kwargs):
        obj = get_object_or_404(self.model, pk=self.kwargs["pk"])
        records = list(obj.history.all().order_by("-history_date"))
        rows = []
        for i, record in enumerate(records):
            older = records[i + 1] if i + 1 < len(records) else None
            diff = None
            if older is not None and record.history_type == "~":
                delta = record.diff_against(older)
                diff = delta.changes
            rows.append({"record": record, "diff": diff})
        return render(request, self.template_name, self.common_context(object=obj, rows=rows))


class ReferenceDocumentUsageView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """
    Traceability page for a single ReferenceDocument: every Quotation it's
    linked to, and for each one, the full downstream chain (Proforma
    Invoice, Invoice) it produced, so a person can see at a glance
    everywhere a given supporting file was used across the whole
    Quotation -> Proforma -> Invoice pipeline.
    """
    permission_required = "masters.view_referencedocument"
    template_name = "masters/reference_document_usage.html"

    def get(self, request, *args, **kwargs):
        from .models import ReferenceDocument
        document = get_object_or_404(ReferenceDocument, pk=self.kwargs["pk"])
        quotations = document.quotations.select_related("client").order_by("-date")
        chains = []
        for q in quotations:
            proforma = getattr(q, "proforma", None)
            invoice = getattr(proforma, "invoice", None) if proforma else None
            chains.append({"quotation": q, "proforma": proforma, "invoice": invoice})
        return render(request, self.template_name, {"document": document, "chains": chains})


# -- singletons: CompanyInfo / DocumentSettings ------------------------------
# Not in the registry: there's no list/create/delete for a singleton, just
# a permanent edit-in-place page plus its own change history.

class SingletonUpdateView(LoginRequiredMixin, PermissionRequiredMixin, View):
    template_name = "masters/singleton_form.html"

    def get(self, request, *args, **kwargs):
        obj = self.model.get_solo()
        form = build_master_form({"model": self.model, "fields": self.fields})(instance=obj)
        return render(request, self.template_name, {
            "form": form, "title": self.title, "history_url_name": self.history_url_name,
            "object": obj,
        })

    def post(self, request, *args, **kwargs):
        obj = self.model.get_solo()
        form_class = build_master_form({"model": self.model, "fields": self.fields})
        form = form_class(request.POST, request.FILES, instance=obj)
        if form.is_valid():
            reason = form.cleaned_data.pop("change_reason", "")
            instance = form.save(commit=False)
            if hasattr(instance, "updated_by_id"):
                instance.updated_by = request.user
            instance._change_reason = reason
            instance._history_user = request.user
            instance.save()
            messages.success(request, f"{self.title} updated.")
            return redirect(request.path)
        return render(request, self.template_name, {
            "form": form, "title": self.title, "history_url_name": self.history_url_name,
            "object": obj,
        })


class CompanyInfoUpdateView(SingletonUpdateView):
    permission_required = "masters.change_companyinfo"
    title = "Company Information"
    history_url_name = "masters:company_info_history"
    fields = ["name", "tagline", "address", "phone", "email", "website", "tax_id", "logo", "default_currency"]

    @property
    def model(self):
        from .models import CompanyInfo
        return CompanyInfo


class DocumentSettingsUpdateView(SingletonUpdateView):
    permission_required = "masters.change_documentsettings"
    title = "Document Settings"
    history_url_name = "masters:document_settings_history"
    fields = ["quotation_prefix", "proforma_prefix", "invoice_prefix", "receipt_prefix",
              "default_vat_percentage", "quotation_validity_days", "quotation_terms",
              "invoice_terms", "document_footer_note"]

    @property
    def model(self):
        from .models import DocumentSettings
        return DocumentSettings


class SingletonHistoryView(LoginRequiredMixin, PermissionRequiredMixin, View):
    template_name = "masters/singleton_history.html"

    def get(self, request, *args, **kwargs):
        obj = self.model.get_solo()
        records = list(obj.history.all().order_by("-history_date"))
        rows = []
        for i, record in enumerate(records):
            older = records[i + 1] if i + 1 < len(records) else None
            diff = None
            if older is not None and record.history_type == "~":
                diff = record.diff_against(older).changes
            rows.append({"record": record, "diff": diff})
        return render(request, self.template_name, {"title": self.title, "rows": rows})


class CompanyInfoHistoryView(SingletonHistoryView):
    permission_required = "masters.view_companyinfo"
    title = "Company Information"

    @property
    def model(self):
        from .models import CompanyInfo
        return CompanyInfo


class DocumentSettingsHistoryView(SingletonHistoryView):
    permission_required = "masters.view_documentsettings"
    title = "Document Settings"

    @property
    def model(self):
        from .models import DocumentSettings
        return DocumentSettings





from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from .models import Currency


class CurrencyListView(LoginRequiredMixin, View):
    template_name = "masters/currencies/list.html"

    def get(self, request):
        query = request.GET.get("q", "").strip()

        currencies = Currency.objects.all()

        if query:
            currencies = currencies.filter(
                Q(name__icontains=query)
                | Q(code__icontains=query)
                | Q(symbol__icontains=query)
            )

        return render(
            request,
            self.template_name,
            {
                "currencies": currencies,
                "query": query,
            },
        )


class CurrencyCreateView(LoginRequiredMixin, View):
    template_name = "masters/currencies/form.html"

    def get(self, request):
        return render(
            request,
            self.template_name,
            {
                "currency": None,
            },
        )

    def post(self, request):
        name = request.POST.get("name", "").strip()
        code = request.POST.get("code", "").strip().upper()
        symbol = request.POST.get("symbol", "").strip()
        exchange_rate = request.POST.get("exchange_rate", "1").strip()
        is_active = request.POST.get("is_active") == "on"

        errors = {}

        if not name:
            errors["name"] = "Currency name is required."

        if not code:
            errors["code"] = "Currency code is required."
        elif len(code) != 3:
            errors["code"] = "Currency code must be 3 characters."
        elif Currency.objects.filter(code=code).exists():
            errors["code"] = "This currency code already exists."

        if not symbol:
            errors["symbol"] = "Currency symbol is required."

        if not exchange_rate:
            errors["exchange_rate"] = "Exchange rate is required."

        if errors:
            return render(
                request,
                self.template_name,
                {
                    "currency": None,
                    "errors": errors,
                    "form_data": request.POST,
                },
            )

        currency = Currency(
            name=name,
            code=code,
            symbol=symbol,
            exchange_rate=exchange_rate,
            is_active=is_active,
        )

        if hasattr(currency, "created_by_id"):
            currency.created_by = request.user

        if hasattr(currency, "updated_by_id"):
            currency.updated_by = request.user

        if hasattr(currency, "_history_user"):
            currency._history_user = request.user

        currency.save()

        messages.success(
            request,
            f"Currency '{currency.code}' created successfully.",
        )

        return redirect("masters:currency_list")


class CurrencyUpdateView(LoginRequiredMixin, View):
    template_name = "masters/currencies/form.html"

    def get_currency(self, pk):
        return get_object_or_404(Currency, pk=pk)

    def get(self, request, pk):
        currency = self.get_currency(pk)

        return render(
            request,
            self.template_name,
            {
                "currency": currency,
            },
        )

    def post(self, request, pk):
        currency = self.get_currency(pk)

        name = request.POST.get("name", "").strip()
        code = request.POST.get("code", "").strip().upper()
        symbol = request.POST.get("symbol", "").strip()
        exchange_rate = request.POST.get("exchange_rate", "1").strip()
        is_active = request.POST.get("is_active") == "on"

        errors = {}

        if not name:
            errors["name"] = "Currency name is required."

        if not code:
            errors["code"] = "Currency code is required."
        elif len(code) != 3:
            errors["code"] = "Currency code must be 3 characters."
        elif Currency.objects.filter(
            code=code
        ).exclude(pk=currency.pk).exists():
            errors["code"] = "This currency code already exists."

        if not symbol:
            errors["symbol"] = "Currency symbol is required."

        if not exchange_rate:
            errors["exchange_rate"] = "Exchange rate is required."

        if errors:
            return render(
                request,
                self.template_name,
                {
                    "currency": currency,
                    "errors": errors,
                    "form_data": request.POST,
                },
            )

        currency.name = name
        currency.code = code
        currency.symbol = symbol
        currency.exchange_rate = exchange_rate
        currency.is_active = is_active

        if hasattr(currency, "updated_by_id"):
            currency.updated_by = request.user

        if hasattr(currency, "_history_user"):
            currency._history_user = request.user

        currency.save()

        messages.success(
            request,
            f"Currency '{currency.code}' updated successfully.",
        )

        return redirect("masters:currency_list")


class CurrencyDeleteView(LoginRequiredMixin, View):

    def post(self, request, pk):
        currency = get_object_or_404(Currency, pk=pk)

        code = currency.code

        try:
            currency.delete()

            messages.success(
                request,
                f"Currency '{code}' deleted successfully.",
            )

        except Exception:
            messages.error(
                request,
                f"Currency '{code}' cannot be deleted because it is "
                f"being used by other records.",
            )

        return redirect("masters:currency_list")


from django.db.models import Q
class PaymentTermListView(LoginRequiredMixin, View):
    template_name = "masters/payment_terms/list.html"

    def get(self, request):
        query = request.GET.get("q", "").strip()

        payment_terms = PaymentTerm.objects.all()

        if query:
            payment_terms = payment_terms.filter(
                Q(name__icontains=query)
                | Q(description__icontains=query)
            )

        return render(
            request,
            self.template_name,
            {
                "payment_terms": payment_terms,
                "query": query,
            },
        )


class PaymentTermCreateView(LoginRequiredMixin, View):
    template_name = "masters/payment_terms/form.html"

    def get(self, request):
        return render(
            request,
            self.template_name,
            {
                "payment_term": None,
            },
        )

    def post(self, request):
        name = request.POST.get("name", "").strip()
        days = request.POST.get("days", "0").strip()
        description = request.POST.get("description", "").strip()
        is_active = request.POST.get("is_active") == "on"

        errors = {}

        if not name:
            errors["name"] = "Payment term name is required."

        try:
            days = int(days)
            if days < 0:
                errors["days"] = "Days cannot be negative."
        except (TypeError, ValueError):
            errors["days"] = "Enter a valid number of days."

        if errors:
            return render(
                request,
                self.template_name,
                {
                    "payment_term": None,
                    "errors": errors,
                    "form_data": request.POST,
                },
            )

        payment_term = PaymentTerm(
            name=name,
            days=days,
            description=description,
            is_active=is_active,
        )

        if hasattr(payment_term, "created_by_id"):
            payment_term.created_by = request.user

        if hasattr(payment_term, "updated_by_id"):
            payment_term.updated_by = request.user

        payment_term._history_user = request.user
        payment_term.save()

        messages.success(
            request,
            f"Payment term '{payment_term.name}' created successfully.",
        )

        return redirect("masters:payment_term_list")


class PaymentTermUpdateView(LoginRequiredMixin, View):
    template_name = "masters/payment_terms/form.html"

    def get_payment_term(self, pk):
        return get_object_or_404(PaymentTerm, pk=pk)

    def get(self, request, pk):
        payment_term = self.get_payment_term(pk)

        return render(
            request,
            self.template_name,
            {
                "payment_term": payment_term,
            },
        )

    def post(self, request, pk):
        payment_term = self.get_payment_term(pk)

        name = request.POST.get("name", "").strip()
        days = request.POST.get("days", "0").strip()
        description = request.POST.get("description", "").strip()
        is_active = request.POST.get("is_active") == "on"

        errors = {}

        if not name:
            errors["name"] = "Payment term name is required."

        try:
            days = int(days)
            if days < 0:
                errors["days"] = "Days cannot be negative."
        except (TypeError, ValueError):
            errors["days"] = "Enter a valid number of days."

        if errors:
            return render(
                request,
                self.template_name,
                {
                    "payment_term": payment_term,
                    "errors": errors,
                    "form_data": request.POST,
                },
            )

        payment_term.name = name
        payment_term.days = days
        payment_term.description = description
        payment_term.is_active = is_active

        if hasattr(payment_term, "updated_by_id"):
            payment_term.updated_by = request.user

        payment_term._history_user = request.user
        payment_term.save()

        messages.success(
            request,
            f"Payment term '{payment_term.name}' updated successfully.",
        )

        return redirect("masters:payment_term_list")


class PaymentTermDeleteView(LoginRequiredMixin, View):

    def post(self, request, pk):
        payment_term = get_object_or_404(PaymentTerm, pk=pk)

        name = payment_term.name

        try:
            payment_term.delete()

            messages.success(
                request,
                f"Payment term '{name}' deleted successfully.",
            )

        except ProtectedError:
            messages.error(
                request,
                f"Payment term '{name}' cannot be deleted because it is "
                f"being used by other records.",
            )

        return redirect("masters:payment_term_list")


from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from .models import ReferenceDocument
class ReferenceDocumentListView(LoginRequiredMixin, View):
    template_name = "masters/reference_documents/list.html"

    def get(self, request):
        query = request.GET.get("q", "").strip()

        documents = ReferenceDocument.objects.all()

        if query:
            documents = documents.filter(
                Q(name__icontains=query)
                | Q(description__icontains=query)
            )

        documents = documents.prefetch_related(
            "quotations"
        )

        return render(
            request,
            self.template_name,
            {
                "documents": documents,
                "query": query,
            },
        )


class ReferenceDocumentDetailView(LoginRequiredMixin, View):
    template_name = "masters/reference_documents/detail.html"

    def get(self, request, pk):
        document = get_object_or_404(
            ReferenceDocument,
            pk=pk,
        )

        quotations = (
            document.quotations
            .select_related("client")
            .order_by("-date")
        )

        chains = []

        for quotation in quotations:

            proforma = getattr(
                quotation,
                "proforma",
                None,
            )

            invoice = (
                getattr(proforma, "invoice", None)
                if proforma
                else None
            )

            chains.append(
                {
                    "quotation": quotation,
                    "proforma": proforma,
                    "invoice": invoice,
                }
            )

        return render(
            request,
            self.template_name,
            {
                "document": document,
                "chains": chains,
            },
        )