"""
expenses app: operating/administrative expense tracking and the payments
made to suppliers against those expenses.

Design notes
------------
- ExpenseCategory has a `category_type` (Operations / Administration) per
  the spec's grouping (Operations: Transport, Fuel, Warehouse, Customs;
  Administration: Rent, Utilities, Salaries). The specific category names
  are ordinary rows, not hardcoded choices, so new categories can be added
  from the admin without a code change; `setup_default_categories` (a
  management command) seeds the ones named in the spec.
- Expense gets the same lightweight Draft -> Submitted -> Approved/Rejected
  workflow used by quotations/proforma, since the spec calls out "Approved
  by" as a field -- that implies an approval step, not just a free-text
  label. `approve_expense` is a custom permission (already referenced by
  Phase 1's setup_groups for the Accountant role).
- VAT is a single percentage per expense (unlike quotations' per-line VAT --
  an expense is one transaction with one supplier invoice behind it, not a
  multi-line document), producing `vat_amount` and `total_amount`.
- SupplierPayment always references a specific Expense (per the spec's
  field list: Supplier, Expense, Amount, Payment date, Reference) and can
  only be recorded once that Expense is Approved. The same overpayment
  guard pattern from invoicing.Payment is reused here: `clean()` for the
  form/admin path, plus a `select_for_update()`-locked check in `save()` so
  two concurrent supplier payments against the same expense can't jointly
  exceed its total.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from core.models import AuditModel, DocumentSequence
from masters.models import Currency, Supplier


class ExpenseCategory(AuditModel):
    class CategoryType(models.TextChoices):
        OPERATIONS = "operations", "Operations"
        ADMINISTRATION = "administration", "Administration"

    name = models.CharField(max_length=100)
    category_type = models.CharField(max_length=20, choices=CategoryType.choices)
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["category_type", "name"]
        verbose_name_plural = "Expense Categories"
        unique_together = ("name", "category_type")

    def __str__(self):
        return f"{self.name} ({self.get_category_type_display()})"


class Expense(AuditModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    expense_number = models.CharField(max_length=30, unique=True, blank=True)
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name="expenses")
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, null=True, blank=True, related_name="expenses",
        help_text="Leave blank for internal expenses with no supplier (e.g. salaries).",
    )
    date = models.DateField(default=timezone.localdate)
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="expenses")
    vat_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    attachment = models.FileField(upload_to="expenses/%Y/%m/", null=True, blank=True)

    status = models.CharField(max_length=15, choices=Status.choices, default=Status.DRAFT)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="expenses_approved",
    )

    class Meta:
        ordering = ["-date", "-id"]
        permissions = [
            ("approve_expense", "Can approve expense"),
        ]

    def __str__(self):
        return self.expense_number or f"Expense #{self.pk}"

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse("expenses:expense_detail", args=[self.pk])

    def save(self, *args, **kwargs):
        if not self.expense_number:
            year = (self.date or timezone.localdate()).year
            self.expense_number = DocumentSequence.next_number("EXP", year)
        super().save(*args, **kwargs)

    @property
    def vat_amount(self) -> Decimal:
        return ((self.amount or Decimal("0")) * (self.vat_percentage or Decimal("0")) / Decimal("100")).quantize(Decimal("0.01"))

    @property
    def total_amount(self) -> Decimal:
        return (self.amount or Decimal("0")) + self.vat_amount

    @property
    def is_editable(self):
        return self.status == self.Status.DRAFT

    @property
    def paid_amount(self) -> Decimal:
        return self.supplier_payments.aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")

    @property
    def balance_due(self) -> Decimal:
        return self.total_amount - self.paid_amount

    # -- workflow -----------------------------------------------------------

    def submit(self, user=None):
        if self.status != self.Status.DRAFT:
            raise ValidationError("Only Draft expenses can be submitted.")
        self.status = self.Status.SUBMITTED
        self.submitted_at = timezone.now()
        self.updated_by = user
        self.save(update_fields=["status", "submitted_at", "updated_by", "updated_at"])

    def approve(self, user=None):
        if self.status != self.Status.SUBMITTED:
            raise ValidationError("Only Submitted expenses can be approved.")
        self.status = self.Status.APPROVED
        self.approved_at = timezone.now()
        self.approved_by = user
        self.updated_by = user
        self.save(update_fields=["status", "approved_at", "approved_by", "updated_by", "updated_at"])

    def reject(self, user=None):
        if self.status != self.Status.SUBMITTED:
            raise ValidationError("Only Submitted expenses can be rejected.")
        self.status = self.Status.REJECTED
        self.updated_by = user
        self.save(update_fields=["status", "updated_by", "updated_at"])

    def revert_to_draft(self, user=None):
        if self.status not in (self.Status.SUBMITTED, self.Status.REJECTED):
            raise ValidationError("Only Submitted or Rejected expenses can be reverted to Draft.")
        self.status = self.Status.DRAFT
        self.submitted_at = None
        self.updated_by = user
        self.save(update_fields=["status", "submitted_at", "updated_by", "updated_at"])


class SupplierPayment(AuditModel):
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="payments_made")
    expense = models.ForeignKey(Expense, on_delete=models.PROTECT, related_name="supplier_payments")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    payment_date = models.DateField(default=timezone.localdate)
    reference_number = models.CharField(max_length=100, blank=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-payment_date", "-id"]

    def __str__(self):
        return f"Payment of {self.amount} to {self.supplier} for {self.expense}"

    def clean(self):
        if self.amount is None or self.amount <= 0:
            raise ValidationError({"amount": "Payment amount must be greater than zero."})
        if self.expense_id:
            if not self.expense.supplier_id:
                raise ValidationError("This expense has no supplier assigned; supplier payments cannot be recorded against it.")
            if self.expense.status != Expense.Status.APPROVED:
                raise ValidationError("Supplier payments can only be recorded against an Approved expense.")
            already_paid = self.expense.supplier_payments.exclude(pk=self.pk).aggregate(
                total=models.Sum("amount"))["total"] or Decimal("0.00")
            remaining = self.expense.total_amount - already_paid
            if self.amount > remaining:
                raise ValidationError({
                    "amount": f"Payment of {self.amount} exceeds the outstanding balance of {remaining}.",
                })

    def save(self, *args, **kwargs):
        with transaction.atomic():
            expense = Expense.objects.select_for_update().get(pk=self.expense_id)
            if not expense.supplier_id:
                raise ValidationError("This expense has no supplier assigned; supplier payments cannot be recorded against it.")
            if not self.supplier_id:
                self.supplier = expense.supplier
            if expense.status != Expense.Status.APPROVED:
                raise ValidationError("Supplier payments can only be recorded against an Approved expense.")
            already_paid = expense.supplier_payments.exclude(pk=self.pk).aggregate(
                total=models.Sum("amount"))["total"] or Decimal("0.00")
            remaining = expense.total_amount - already_paid
            if self.amount is None or self.amount <= 0:
                raise ValidationError("Payment amount must be greater than zero.")
            if self.amount > remaining:
                raise ValidationError(
                    f"Payment of {self.amount} exceeds the outstanding balance of {remaining}."
                )
            super().save(*args, **kwargs)
