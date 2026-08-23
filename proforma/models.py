"""
proforma app: Proforma Invoice, generated from an Approved Quotation.

Design notes
------------
- ProformaInvoice.quotation is a OneToOneField: per the spec ("PI can only
  be generated from quotation") each quotation converts into at most one
  proforma. The reverse accessor (`quotation.proforma`) is how the UI knows
  whether an approved quotation has already been converted.
- Creation happens ONLY through `ProformaInvoice.create_from_quotation()`,
  never through a bare `ProformaInvoice.objects.create(...)` from a view/
  form. That classmethod is the single place that (a) validates the
  quotation is Approved and not already converted, (b) copies the header
  and line items across as independent rows, and (c) calls
  `quotation.mark_converted()` to lock the quotation. This matches the
  spec's explicit rules: "PI can only be generated from quotation" and
  "Editing PI should not modify quotation" -- copying into separate
  ProformaInvoiceItem rows (rather than referencing the quotation's items)
  makes the independence structural, not just a convention.
- Workflow mirrors Quotation's: Draft -> Submitted -> Approved (+ Reject /
  Revert-to-Draft), and a further `mark_converted()` for when Phase 5's
  Invoice module generates an Invoice from this PI ("PI approval required
  before invoice creation" + "After invoice creation: LOCK Proforma
  Invoice"). Editing is only allowed in Draft.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import AuditModel, DocumentSequence
from masters.models import Client, Currency, Item, PaymentTerm, Port, ReferenceDocument


class ProformaInvoice(AuditModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CONVERTED = "converted", "Converted to Invoice"

    pi_number = models.CharField(max_length=30, unique=True, blank=True)
    quotation = models.OneToOneField(
        "quotations.Quotation", on_delete=models.PROTECT, related_name="proforma",
    )

    # -- copied from the quotation at conversion time, then independent --
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="proforma_invoices")
    date = models.DateField(default=timezone.localdate)
    shipment_type = models.CharField(
        max_length=10,
        choices=[("import", "Import"), ("export", "Export"), ("transit", "Transit")],
        blank=True,
    )
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="proforma_invoices")
    payment_terms = models.ForeignKey(PaymentTerm, on_delete=models.PROTECT, related_name="proforma_invoices")
    sales_representative = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="proforma_invoices",
    )
    origin_port = models.ForeignKey(
        Port, on_delete=models.PROTECT, null=True, blank=True, related_name="proforma_as_origin",
        verbose_name="Origin Port (POL)",
    )
    destination_port = models.ForeignKey(
        Port, on_delete=models.PROTECT, null=True, blank=True, related_name="proforma_as_destination",
        verbose_name="Destination Port (POD)",
    )
    final_destination = models.CharField("Final Point of Delivery (FPOD)", max_length=150, blank=True)
    commodity = models.CharField(
        max_length=150, blank=True, default="",
        help_text="Free text, copied from the quotation at conversion time.",
    )
    commodity_quantity = models.CharField(max_length=50, blank=True)
    commodity_unit = models.CharField(max_length=30, blank=True)
    reference_document = models.ForeignKey(
        ReferenceDocument, on_delete=models.SET_NULL, null=True, blank=True, related_name="proforma_invoices",
    )
    notes = models.TextField(blank=True)
    terms = models.TextField(blank=True)

    # -- proforma-specific shipment fields (per spec) --
    bl_number = models.CharField("BL Number", max_length=50, blank=True)
    shipment_reference = models.CharField(max_length=50, blank=True)
    container_number = models.CharField(max_length=50, blank=True)
    vessel = models.CharField(max_length=100, blank=True)
    eta = models.DateField("ETA", null=True, blank=True)
    etd = models.DateField("ETD", null=True, blank=True)

    status = models.CharField(max_length=15, choices=Status.choices, default=Status.DRAFT)

    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="proforma_invoices_approved",
    )

    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    vat_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ["-date", "-id"]
        permissions = [
            ("approve_proformainvoice", "Can approve proforma invoice"),
            ("submit_proformainvoice", "Can submit proforma invoice for approval"),
        ]

    def __str__(self):
        return self.pi_number or f"Proforma Invoice #{self.pk}"

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse("proforma:detail", args=[self.pk])

    # -- creation ---------------------------------------------------------

    def save(self, *args, **kwargs):
        if not self.pi_number:
            from masters.models import DocumentSettings
            prefix = DocumentSettings.get_solo().proforma_prefix
            year = (self.date or timezone.localdate()).year
            self.pi_number = DocumentSequence.next_number(prefix, year)
        super().save(*args, **kwargs)

    @classmethod
    def create_from_quotation(cls, quotation, user=None):
        """
        The ONLY supported way to create a ProformaInvoice. Validates the
        quotation is eligible, copies header + line items as independent
        rows, then locks the source quotation.
        """
        if quotation.status != quotation.Status.APPROVED:
            raise ValidationError("Only an Approved quotation can be converted to a Proforma Invoice.")
        if hasattr(quotation, "proforma"):
            raise ValidationError(f"{quotation.quotation_number} has already been converted to a Proforma Invoice.")
        if not quotation.items.exists():
            raise ValidationError("Cannot convert a quotation with no line items.")

        pi = cls(
            quotation=quotation,
            client=quotation.client,
            date=timezone.localdate(),
            shipment_type=quotation.shipment_type,
            currency=quotation.currency,
            payment_terms=quotation.payment_terms,
            sales_representative=quotation.sales_representative,
            origin_port=quotation.origin_port,
            destination_port=quotation.destination_port,
            final_destination=quotation.final_destination,
            commodity=quotation.commodity,
            commodity_quantity=quotation.commodity_quantity,
            commodity_unit=quotation.commodity_unit,
            reference_document=quotation.reference_document,
            notes=quotation.notes,
            terms=quotation.terms,
            created_by=user,
            updated_by=user,
        )
        pi.save()

        for line in quotation.items.all():
            ProformaInvoiceItem.objects.create(
                proforma_invoice=pi,
                item=line.item,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
                vat_percentage=line.vat_percentage,
            )
        pi.recalculate_totals()

        quotation.mark_converted(user=user)
        return pi

    # -- editability / workflow -------------------------------------------

    @property
    def is_editable(self):
        return self.status == self.Status.DRAFT

    @property
    def is_locked(self):
        return self.status == self.Status.CONVERTED

    def submit(self, user=None):
        if self.status != self.Status.DRAFT:
            raise ValidationError("Only Draft proforma invoices can be submitted.")
        if not self.items.exists():
            raise ValidationError("Cannot submit a proforma invoice with no line items.")
        self.status = self.Status.SUBMITTED
        self.submitted_at = timezone.now()
        self.updated_by = user
        self.save(update_fields=["status", "submitted_at", "updated_by", "updated_at"])

    def approve(self, user=None):
        if self.status != self.Status.SUBMITTED:
            raise ValidationError("Only Submitted proforma invoices can be approved.")
        self.status = self.Status.APPROVED
        self.approved_at = timezone.now()
        self.approved_by = user
        self.updated_by = user
        self.save(update_fields=["status", "approved_at", "approved_by", "updated_by", "updated_at"])

    def reject(self, user=None):
        if self.status != self.Status.SUBMITTED:
            raise ValidationError("Only Submitted proforma invoices can be rejected.")
        self.status = self.Status.REJECTED
        self.updated_by = user
        self.save(update_fields=["status", "updated_by", "updated_at"])

    def revert_to_draft(self, user=None):
        if self.status not in (self.Status.SUBMITTED, self.Status.REJECTED):
            raise ValidationError("Only Submitted or Rejected proforma invoices can be reverted to Draft.")
        self.status = self.Status.DRAFT
        self.submitted_at = None
        self.updated_by = user
        self.save(update_fields=["status", "submitted_at", "updated_by", "updated_at"])

    def mark_converted(self, user=None):
        """Called by the invoicing app (Phase 5) once an Invoice has been
        generated from this proforma. Locks it permanently, per the spec's
        "After invoice creation: LOCK ... Proforma Invoice" rule."""
        if self.status != self.Status.APPROVED:
            raise ValidationError("Only an Approved proforma invoice can be converted to an Invoice.")
        self.status = self.Status.CONVERTED
        self.updated_by = user
        self.save(update_fields=["status", "updated_by", "updated_at"])

    # -- totals -------------------------------------------------------------

    def recalculate_totals(self, save=True):
        items = list(self.items.all())
        subtotal = sum((i.line_subtotal for i in items), Decimal("0.00"))
        vat_total = sum((i.vat_amount for i in items), Decimal("0.00"))
        self.subtotal = subtotal
        self.vat_total = vat_total
        self.grand_total = subtotal + vat_total
        if save:
            super(ProformaInvoice, self).save(
                update_fields=["subtotal", "vat_total", "grand_total", "updated_at"]
            )


class ProformaInvoiceItem(models.Model):
    proforma_invoice = models.ForeignKey(ProformaInvoice, on_delete=models.CASCADE, related_name="items")
    item = models.ForeignKey(
        Item, on_delete=models.PROTECT, null=True, blank=True, related_name="proforma_lines",
    )
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
        self.proforma_invoice.recalculate_totals()

    def delete(self, *args, **kwargs):
        pi = self.proforma_invoice
        super().delete(*args, **kwargs)
        pi.recalculate_totals()
