"""
quotations app: the first document in the business flow
(Master Data -> Quotation -> Proforma Invoice -> Invoice -> Payments ->
Receipt -> Statement of Account).

Design notes
------------
- Quotation.quotation_number is claimed from core.DocumentSequence at
  creation time (not on "submit"), using the configured prefix from
  masters.DocumentSettings and the quotation's date year. Generating it
  immediately (rather than only once approved) matches how these numbers
  are used in practice as a reference from the moment the document exists,
  as illustrated by the sample "QTN-2026-0001" reference document supplied.
- Selecting a Client should auto-populate currency/payment terms/sales rep/
  billing info (per the spec). That auto-populate happens client-side via
  masters' `client_autofill` JSON endpoint (Phase 2) -- the model itself
  simply stores whatever values were submitted, and `populate_from_client()`
  is provided as a server-side convenience (used by the create view before
  first save, and by tests) so the behaviour isn't solely reliant on JS.
- Commodity/route fields (origin_port, destination_port, final_destination,
  commodity, commodity_quantity, commodity_unit) mirror the reference
  quotation PDF's COMMODITY / POL / POD / QTY / FPOD row. These describe the
  shipment as a whole; QuotationItem rows are the separate billable line
  items (Freight, Clearance fee, etc.) per the spec's explicit "Quotation
  Items: Separate from commodity" instruction.
- Workflow is Draft -> Submitted -> Approved -> Converted (to Proforma
  Invoice in Phase 4). Transitions are enforced by service methods
  (submit/approve/reject/revert_to_draft/mark_converted) rather than letting
  `status` be set directly by a form, so invalid jumps (e.g. Draft ->
  Converted) can't happen through the UI. Editing line items or header
  fields is only allowed while status == DRAFT; this is enforced in the
  views/forms layer (QuotationEditableMixin) rather than the model, since
  the admin still needs unrestricted access for corrections.
- VAT is computed per line (copying the rate from the selected Item at the
  time it's added, so later changes to the item's VAT % don't silently
  rewrite historical quotations), then summed for the header's vat_total.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from core.models import AuditModel, DocumentSequence
from masters.models import Client, Currency, Item, PaymentTerm, Port, ReferenceDocument


class Quotation(AuditModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CONVERTED = "converted", "Converted to Proforma"

    class ShipmentType(models.TextChoices):
        IMPORT = "import", "Import"
        EXPORT = "export", "Export"
        TRANSIT = "transit", "Transit"

    quotation_number = models.CharField(max_length=30, unique=True, blank=True)

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="quotations")
    date = models.DateField(default=timezone.localdate)
    valid_until = models.DateField(null=True, blank=True)
    shipment_type = models.CharField(
        max_length=10, choices=ShipmentType.choices, blank=True,
        help_text="Whether this shipment is an Import, Export, or Transit movement.",
    )

    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="quotations")
    payment_terms = models.ForeignKey(PaymentTerm, on_delete=models.PROTECT, related_name="quotations")
    sales_representative = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="quotations",
    )

    origin_port = models.ForeignKey(
        Port, on_delete=models.PROTECT, null=True, blank=True, related_name="quotations_as_origin",
        verbose_name="Origin Port (POL)",
    )
    destination_port = models.ForeignKey(
        Port, on_delete=models.PROTECT, null=True, blank=True, related_name="quotations_as_destination",
        verbose_name="Destination Port (POD)",
    )
    final_destination = models.CharField(
        "Final Point of Delivery (FPOD)", max_length=150, blank=True, default="",
    )
    commodity = models.CharField(
        max_length=150, blank=True, default="",
        help_text="Free text, e.g. 'Flowers', 'Machinery'. Not restricted to a master list -- "
                   "the form offers existing values as suggestions but accepts anything typed.",
    )
    commodity_quantity = models.CharField(max_length=50, blank=True, help_text="e.g. '1', '20ft x2'")
    commodity_unit = models.CharField(max_length=30, blank=True, help_text="e.g. unit, ton, CBM")

    status = models.CharField(max_length=15, choices=Status.choices, default=Status.DRAFT)

    reference_document = models.ForeignKey(
        ReferenceDocument, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="quotations",
        help_text="Optional: link a supporting file (client PO, correspondence, etc.) "
                   "instead of typing a reference number. Upload it under Master Data first.",
    )
    notes = models.TextField(blank=True)
    terms = models.TextField(blank=True, help_text="Printed terms & conditions; defaults from Document Settings.")

    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="quotations_approved",
    )

    # Denormalized totals, recalculated by recalculate_totals() whenever
    # line items change. Stored (not computed on every read) so list views
    # and statements don't need to aggregate line items every time.
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    vat_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    grand_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ["-date", "-id"]
        permissions = [
            ("approve_quotation", "Can approve quotation"),
            ("submit_quotation", "Can submit quotation for approval"),
        ]

    def __str__(self):
        return self.quotation_number or f"Quotation #{self.pk}"

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse("quotations:detail", args=[self.pk])

    # -- creation / numbering -------------------------------------------------

    def save(self, *args, **kwargs):
        if not self.quotation_number:
            from masters.models import DocumentSettings
            prefix = DocumentSettings.get_solo().quotation_prefix
            year = (self.date or timezone.localdate()).year
            self.quotation_number = DocumentSequence.next_number(prefix, year)
        super().save(*args, **kwargs)

    def populate_from_client(self):
        """Server-side mirror of the client-autofill JS behaviour; safe to
        call before the first save if currency/payment_terms/sales_rep were
        left unset."""
        if not self.client_id:
            return
        payload = self.client.autofill_payload()
        if not self.currency_id:
            self.currency_id = payload["currency_id"]
        if not self.payment_terms_id:
            self.payment_terms_id = payload["payment_terms_id"]
        if not self.sales_representative_id:
            self.sales_representative_id = payload["sales_representative_id"]

    # -- editability / workflow ------------------------------------------------

    @property
    def is_editable(self):
        return self.status == self.Status.DRAFT

    @property
    def is_locked(self):
        return self.status == self.Status.CONVERTED

    def submit(self, user=None):
        if self.status != self.Status.DRAFT:
            raise ValidationError("Only Draft quotations can be submitted.")
        if not self.items.exists():
            raise ValidationError("Cannot submit a quotation with no line items.")
        self.status = self.Status.SUBMITTED
        self.submitted_at = timezone.now()
        self.updated_by = user
        self.save(update_fields=["status", "submitted_at", "updated_by", "updated_at"])

    def approve(self, user=None):
        if self.status != self.Status.SUBMITTED:
            raise ValidationError("Only Submitted quotations can be approved.")
        self.status = self.Status.APPROVED
        self.approved_at = timezone.now()
        self.approved_by = user
        self.updated_by = user
        self.save(update_fields=["status", "approved_at", "approved_by", "updated_by", "updated_at"])

    def reject(self, user=None):
        if self.status != self.Status.SUBMITTED:
            raise ValidationError("Only Submitted quotations can be rejected.")
        self.status = self.Status.REJECTED
        self.updated_by = user
        self.save(update_fields=["status", "updated_by", "updated_at"])

    def revert_to_draft(self, user=None):
        if self.status not in (self.Status.SUBMITTED, self.Status.REJECTED):
            raise ValidationError("Only Submitted or Rejected quotations can be reverted to Draft.")
        self.status = self.Status.DRAFT
        self.submitted_at = None
        self.updated_by = user
        self.save(update_fields=["status", "submitted_at", "updated_by", "updated_at"])

    def mark_converted(self, user=None):
        """Called by the proforma app (Phase 4) once a Proforma Invoice has
        been generated from this quotation. Locks the quotation permanently."""
        if self.status != self.Status.APPROVED:
            raise ValidationError("Only Approved quotations can be converted to a Proforma Invoice.")
        self.status = self.Status.CONVERTED
        self.updated_by = user
        self.save(update_fields=["status", "updated_by", "updated_at"])

    # -- totals -----------------------------------------------------------------

    def recalculate_totals(self, save=True):
        items = list(self.items.all())
        subtotal = sum((i.line_subtotal for i in items), Decimal("0.00"))
        vat_total = sum((i.vat_amount for i in items), Decimal("0.00"))
        self.subtotal = subtotal
        self.vat_total = vat_total
        self.grand_total = subtotal + vat_total
        if save:
            super(Quotation, self).save(
                update_fields=["subtotal", "vat_total", "grand_total", "updated_at"]
            )


class QuotationItem(models.Model):
    quotation = models.ForeignKey(Quotation, on_delete=models.CASCADE, related_name="items")
    item = models.ForeignKey(
        Item, on_delete=models.PROTECT, null=True, blank=True, related_name="quotation_lines",
        help_text="Optional link to a master Item; pre-fills description/price/VAT.",
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

    def populate_from_item(self):
        if self.item_id and not self.description:
            self.description = self.item.description or self.item.name
        if self.item_id and not self.unit_price:
            self.unit_price = self.item.selling_price
        if self.item_id and self.vat_percentage == 0 and self.item.vat_applicable:
            self.vat_percentage = self.item.vat_percentage

    def save(self, *args, **kwargs):
        self.populate_from_item()
        super().save(*args, **kwargs)
        # Keep header totals in sync whenever a line item is written.
        self.quotation.recalculate_totals()

    def delete(self, *args, **kwargs):
        quotation = self.quotation
        super().delete(*args, **kwargs)
        quotation.recalculate_totals()
