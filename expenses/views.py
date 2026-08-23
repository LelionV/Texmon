"""
Expense / SupplierPayment views.

Visibility: unlike quotations (which restrict Sales Reps to their own
clients), expenses have no natural "owner" concept in the spec beyond
created_by, so visibility is permission-gated only (view_expense) rather
than filtered by user -- Accountant/Finance Officer/Administrator are
expected to see the full expense ledger to do their jobs.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from accounts.models import UserActivityLog
from .forms import ExpenseForm, SupplierPaymentForm
from .models import Expense, SupplierPayment


class ExpenseListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = Expense
    template_name = "expenses/expense_list.html"
    context_object_name = "expenses"
    paginate_by = 25
    permission_required = "expenses.view_expense"

    def get_queryset(self):
        qs = Expense.objects.select_related("category", "supplier", "currency").order_by("-date", "-id")
        status = self.request.GET.get("status")
        category = self.request.GET.get("category")
        q = self.request.GET.get("q")
        if status:
            qs = qs.filter(status=status)
        if category:
            qs = qs.filter(category_id=category)
        if q:
            qs = qs.filter(expense_number__icontains=q) | qs.filter(description__icontains=q)
        return qs

    def get_context_data(self, **kwargs):
        from .models import ExpenseCategory
        ctx = super().get_context_data(**kwargs)
        ctx["status_choices"] = Expense.Status.choices
        ctx["categories"] = ExpenseCategory.objects.filter(is_active=True)
        ctx["current_status"] = self.request.GET.get("status", "")
        ctx["current_category"] = self.request.GET.get("category", "")
        ctx["q"] = self.request.GET.get("q", "")
        return ctx


class ExpenseDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = Expense
    template_name = "expenses/expense_detail.html"
    context_object_name = "expense"
    permission_required = "expenses.view_expense"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["payments"] = self.object.supplier_payments.select_related("supplier")
        ctx["payment_form"] = SupplierPaymentForm(initial={"amount": self.object.balance_due})
        return ctx


class ExpenseCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    model = Expense
    form_class = ExpenseForm
    template_name = "expenses/expense_form.html"
    permission_required = "expenses.add_expense"

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        form.instance.updated_by = self.request.user
        response = super().form_valid(form)
        UserActivityLog.log(self.request.user, UserActivityLog.Action.CREATE,
                             f"Created expense {self.object.expense_number}", obj=self.object, request=self.request)
        messages.success(self.request, f"Expense {self.object.expense_number} created.")
        return response


class ExpenseUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    model = Expense
    form_class = ExpenseForm
    template_name = "expenses/expense_form.html"
    permission_required = "expenses.change_expense"

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        if not self.object.is_editable:
            messages.error(request, f"{self.object.expense_number} is {self.object.get_status_display()} and can no longer be edited.")
            return redirect(self.object.get_absolute_url())
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.updated_by = self.request.user
        response = super().form_valid(form)
        UserActivityLog.log(self.request.user, UserActivityLog.Action.UPDATE,
                             f"Updated expense {self.object.expense_number}", obj=self.object, request=self.request)
        messages.success(self.request, f"{self.object.expense_number} updated.")
        return response


# -- workflow transitions -----------------------------------------------------

def _transition(request, pk, action, log_action, success_msg):
    expense = get_object_or_404(Expense, pk=pk)
    try:
        getattr(expense, action)(user=request.user)
        UserActivityLog.log(request.user, log_action, success_msg.format(expense), obj=expense, request=request)
        messages.success(request, success_msg.format(expense))
    except ValidationError as e:
        messages.error(request, "; ".join(e.messages) if hasattr(e, "messages") else str(e))
    return redirect(expense.get_absolute_url())


@login_required
@permission_required("expenses.change_expense", raise_exception=True)
def submit_expense(request, pk):
    return _transition(request, pk, "submit", UserActivityLog.Action.SUBMIT, "{} submitted for approval.")


@login_required
@permission_required("expenses.approve_expense", raise_exception=True)
def approve_expense(request, pk):
    return _transition(request, pk, "approve", UserActivityLog.Action.APPROVE, "{} approved.")


@login_required
@permission_required("expenses.approve_expense", raise_exception=True)
def reject_expense(request, pk):
    return _transition(request, pk, "reject", UserActivityLog.Action.REJECT, "{} rejected.")


@login_required
@permission_required("expenses.change_expense", raise_exception=True)
def revert_expense(request, pk):
    return _transition(request, pk, "revert_to_draft", UserActivityLog.Action.UPDATE, "{} reverted to Draft.")


# -- supplier payments ----------------------------------------------------

@login_required
@permission_required("expenses.add_supplierpayment", raise_exception=True)
@require_POST
def add_supplier_payment(request, expense_pk):
    expense = get_object_or_404(Expense, pk=expense_pk)
    if not expense.supplier_id:
        messages.error(request, f"{expense.expense_number} has no supplier assigned; supplier payments cannot be recorded against it.")
        return redirect(expense.get_absolute_url())
    form = SupplierPaymentForm(request.POST)
    if form.is_valid():
        payment = form.save(commit=False)
        payment.expense = expense
        payment.supplier = expense.supplier
        payment.created_by = request.user
        payment.updated_by = request.user
        try:
            payment.save()
            UserActivityLog.log(request.user, UserActivityLog.Action.PAYMENT,
                                 f"Recorded supplier payment of {payment.amount} on {expense.expense_number}",
                                 obj=expense, request=request)
            messages.success(request, f"Payment of {expense.currency.symbol}{payment.amount} recorded.")
        except ValidationError as e:
            messages.error(request, "; ".join(e.messages) if hasattr(e, "messages") else str(e))
    else:
        for field, errors in form.errors.items():
            for err in errors:
                messages.error(request, f"{field}: {err}")
    return redirect(expense.get_absolute_url())


class SupplierPaymentListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = SupplierPayment
    template_name = "expenses/supplier_payment_list.html"
    context_object_name = "payments"
    paginate_by = 25
    permission_required = "expenses.view_supplierpayment"

    def get_queryset(self):
        return SupplierPayment.objects.select_related("supplier", "expense").order_by("-payment_date", "-id")
