"""
invoicing app: Invoice (generated from an Approved Proforma Invoice),
Payment (with balance tracking and an overpayment guard), and Receipt
(auto-generated after every payment).

Design notes
------------
- Invoice.proforma_invoice is a OneToOneField, mirroring the PI<->Quotation
  relationship in Phase 4: an Invoice can only come from one PI, and
  `Invoice.create_from_proforma()` is the only supported creation path.
  Per the spec's "After invoice creation: LOCK Quotation, Proforma Invoice",
  that classmethod calls `proforma.mark_converted()` (the quotation is
  already locked -- it was converted when the PI itself was created in
  Phase 4, and stays that way).
- Unlike Quotation/PI, Invoice has no Draft/Submitted/Approved workflow of
  its own -- the spec doesn't call for one, since approval already happened
  at the PI stage. Once created, an invoice's header and line items are
  fixed; the only things that change afterwards are payments recorded
  against it (which update `paid_amount`/`balance_due`/`status`) and the
  generated PDF. There is deliberately no InvoiceUpdateView.
- Payment enforces "cannot pay more than invoice balance" in `clean()` *and*
  again inside `save()`'s locked transaction (belt-and-braces: `clean()`
  guards the form/admin path, the transaction guards any programmatic path
  and prevents a race between two concurrent payments on the same invoice).
  Saving a new Payment atomically updates the invoice's `paid_amount` /
  `balance_due` / `status`, then creates the matching Receipt in the same
  transaction, so a Payment can never exist without its Receipt.
- Receipt.receipt_number uses the same core.DocumentSequence numbering
  scheme as the other documents (RCPT-YYYY-0001).
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.dispatch import Signal
from django.utils import timezone

from core.models import AuditModel, DocumentSequence
from masters.models import Client, Currency, Item, PaymentTerm, Port, ReferenceDocument

# Fired once, after an Invoice has been fully created AND its totals have
# been finalized (see Invoice.create_from_proforma) -- NOT on every
# Invoice.save(). A plain post_save signal fires too early here: the
# Invoice row is first saved (to get a pk for its line items) while
# grand_total is still 0, and only reaches its real total after the line
# items are copied over and recalculate_totals() runs. Anything that needs
# the invoice's final state (e.g. accounting posting a ledger entry) should
# listen to this signal instead of post_save.
# Sent with keyword argument `invoice`.
invoice_finalized = Signal()


class Invoice(AuditModel):
    class Status(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PARTIALLY_PAID = "partially_paid", "Partially Paid"
        PAID = "paid", "Paid"
        CANCELLED = "cancelled", "Cancelled"

    invoice_number = models.CharField(max_length=30, unique=True, blank=True)
    proforma_invoice = models.OneToOneField(
        "proforma.ProformaInvoice", on_delete=models.PROTECT, related_name="invoice",
    )

    # -- copied from the proforma invoice at creation time, then independent --
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="invoices")
    shipment_type = models.CharField(
        max_length=10,
        choices=[("import", "Import"), ("export", "Export"), ("transit", "Transit")],
        blank=True,
    )
    date = models.DateField(default=timezone.localdate)
    due_date = models.DateField(null=True, blank=True)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="invoices")
    payment_terms = models.ForeignKey(PaymentTerm, on_delete=models.PROTECT, related_name="invoices")
    sales_representative = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="invoices",
    )
    origin_port = models.ForeignKey(Port, on_delete=models.PROTECT, null=True, blank=True, related_name="invoices_as_origin")
    destination_port = models.ForeignKey(Port, on_delete=models.PROTECT, null=True, blank=True, related_name="invoices_as_destination")
    final_destination = models.CharField(max_length=150, blank=True)
    commodity = models.CharField(
        max_length=150, blank=True, default="",
        help_text="Free text, copied from the proforma invoice at invoice creation.",
    )
    bl_number = models.CharField("BL Number", max_length=50, blank=True)
    container_number = models.CharField(max_length=50, blank=True)
    vessel = models.CharField(max_length=100, blank=True)

    reference_document = models.ForeignKey(
        ReferenceDocument, on_delete=models.SET_NULL, null=True, blank=True, related_name="invoices",
    )
    notes = models.TextField(blank=True)
    terms = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UNPAID)

    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    vat_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    balance_due = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.invoice_number or f"Invoice #{self.pk}"

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse("invoicing:invoice_detail", args=[self.pk])

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            from masters.models import DocumentSettings
            prefix = DocumentSettings.get_solo().invoice_prefix
            year = (self.date or timezone.localdate()).year
            self.invoice_number = DocumentSequence.next_number(prefix, year)
        super().save(*args, **kwargs)

    @classmethod
    def create_from_proforma(cls, proforma, user=None):
        """The ONLY supported way to create an Invoice. Validates the PI is
        Approved and not already invoiced, copies header + line items as
        independent rows, then locks the proforma (the quotation is already
        locked from the PI-creation step in Phase 4)."""
        if proforma.status != proforma.Status.APPROVED:
            raise ValidationError("Only an Approved proforma invoice can be converted to an Invoice.")
        if hasattr(proforma, "invoice"):
            raise ValidationError(f"{proforma.pi_number} has already been converted to an Invoice.")
        if not proforma.items.exists():
            raise ValidationError("Cannot invoice a proforma invoice with no line items.")

        invoice_date = timezone.localdate()
        due_date = invoice_date + timezone.timedelta(days=proforma.payment_terms.days)

        invoice = cls(
            proforma_invoice=proforma,
            client=proforma.client,
            date=invoice_date,
            due_date=due_date,
            shipment_type=proforma.shipment_type,
            currency=proforma.currency,
            payment_terms=proforma.payment_terms,
            sales_representative=proforma.sales_representative,
            origin_port=proforma.origin_port,
            destination_port=proforma.destination_port,
            final_destination=proforma.final_destination,
            commodity=proforma.commodity,
            bl_number=proforma.bl_number,
            container_number=proforma.container_number,
            vessel=proforma.vessel,
            reference_document=proforma.reference_document,
            notes=proforma.notes,
            terms=proforma.terms,
            created_by=user,
            updated_by=user,
        )
        invoice.save()

        for line in proforma.items.all():
            InvoiceItem.objects.create(
                invoice=invoice,
                item=line.item,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                vat_percentage=line.vat_percentage,
            )
        invoice.recalculate_totals()

        proforma.mark_converted(user=user)
        invoice_finalized.send(sender=Invoice, invoice=invoice)
        return invoice

    # -- totals / balance --------------------------------------------------

    def recalculate_totals(self, save=True):
        items = list(self.items.all())
        subtotal = sum((i.line_subtotal for i in items), Decimal("0.00"))
        vat_total = sum((i.vat_amount for i in items), Decimal("0.00"))
        self.subtotal = subtotal
        self.vat_total = vat_total
        self.grand_total = subtotal + vat_total
        self.balance_due = self.grand_total - self.paid_amount
        if save:
            super(Invoice, self).save(
                update_fields=["subtotal", "vat_total", "grand_total", "balance_due", "updated_at"]
            )

    def refresh_payment_status(self, save=True):
        """Recompute paid_amount/balance_due/status from actual Payment rows.
        Called inside Payment.save()'s locked transaction."""
        total_paid = self.payments.aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")
        self.paid_amount = total_paid
        self.balance_due = self.grand_total - total_paid
        if total_paid <= 0:
            self.status = self.Status.UNPAID
        elif total_paid < self.grand_total:
            self.status = self.Status.PARTIALLY_PAID
        else:
            self.status = self.Status.PAID
        if save:
            super(Invoice, self).save(update_fields=["paid_amount", "balance_due", "status", "updated_at"])

    @property
    def is_fully_paid(self):
        return self.status == self.Status.PAID


class InvoiceItem(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="items")
    item = models.ForeignKey(Item, on_delete=models.PROTECT, null=True, blank=True, related_name="invoice_lines")
    description = models.CharField(max_length=255)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    vat_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.description} x{self.quantity}"

    @property
    def line_subtotal(self) -> Decimal:
        return (self.quantity or Decimal("0")) * (self.unit_price or Decimal("0"))

    @property
    def vat_amount(self) -> Decimal:
        return (self.line_subtotal * (self.vat_percentage or Decimal("0")) / Decimal("100")).quantize(Decimal("0.01"))

    @property
    def total_amount(self) -> Decimal:
        return self.line_subtotal + self.vat_amount

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.invoice.recalculate_totals()


class Payment(AuditModel):
    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        BANK_TRANSFER = "bank_transfer", "Bank Transfer"
        CHEQUE = "cheque", "Cheque"
        MOBILE_MONEY = "mobile_money", "Mobile Money"
        CREDIT_CARD = "credit_card", "Credit Card"
        OTHER = "other", "Other"

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    payment_date = models.DateField(default=timezone.localdate)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=Method.choices, default=Method.BANK_TRANSFER)
    reference_number = models.CharField(max_length=100, blank=True)
    bank_account = models.CharField("Bank/Account", max_length=100, blank=True)
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-payment_date", "-id"]

    def __str__(self):
        return f"Payment of {self.amount} on {self.invoice}"

    def clean(self):
        if self.amount is None or self.amount <= 0:
            raise ValidationError({"amount": "Payment amount must be greater than zero."})
        if self.invoice_id:
            already_paid = self.invoice.payments.exclude(pk=self.pk).aggregate(
                total=models.Sum("amount"))["total"] or Decimal("0.00")
            remaining = self.invoice.grand_total - already_paid
            if self.amount > remaining:
                raise ValidationError({
                    "amount": f"Payment of {self.amount} exceeds the outstanding balance of {remaining}.",
                })

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        with transaction.atomic():
            invoice = Invoice.objects.select_for_update().get(pk=self.invoice_id)
            already_paid = invoice.payments.exclude(pk=self.pk).aggregate(
                total=models.Sum("amount"))["total"] or Decimal("0.00")
            remaining = invoice.grand_total - already_paid
            if self.amount is None or self.amount <= 0:
                raise ValidationError("Payment amount must be greater than zero.")
            if self.amount > remaining:
                raise ValidationError(
                    f"Payment of {self.amount} exceeds the outstanding balance of {remaining}."
                )
            super().save(*args, **kwargs)
            invoice.refresh_from_db()
            invoice.refresh_payment_status()
            if is_new:
                Receipt.objects.create(
                    payment=self, invoice=invoice, amount=self.amount,
                    date=self.payment_date, created_by=self.created_by,
                )


class Receipt(models.Model):
    receipt_number = models.CharField(max_length=30, unique=True, blank=True)
    payment = models.OneToOneField(Payment, on_delete=models.PROTECT, related_name="receipt")
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="receipts")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    date = models.DateField(default=timezone.localdate)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return self.receipt_number or f"Receipt #{self.pk}"

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse("invoicing:receipt_detail", args=[self.pk])

    def save(self, *args, **kwargs):
        if not self.receipt_number:
            from masters.models import DocumentSettings
            prefix = DocumentSettings.get_solo().receipt_prefix
            year = (self.date or timezone.localdate()).year
            self.receipt_number = DocumentSequence.next_number(prefix, year)
        super().save(*args, **kwargs)
