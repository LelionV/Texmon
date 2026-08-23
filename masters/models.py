"""
masters app: all reference/master data used across quotations, proforma,
invoicing, expenses and accounting.

Design notes
------------
- Every model here inherits core.AuditModel for created/updated tracking,
  since master data is edited by multiple users over time and "who changed
  the exchange rate" / "who added this client" matters.
- Client.currency / Client.payment_terms / Client.sales_representative exist
  specifically so the quotation form (Phase 3) can auto-populate those three
  fields the moment a client is selected, per the spec. `Client.autofill()`
  returns exactly that payload and is also exposed as a small JSON API
  (masters/api.py) for the HTMX/JS quotation form to call.
- "Sales Representative" is NOT a separate master model. Per the spec it's
  just a person who can be assigned to a client/quotation, so it's an FK to
  accounts.User, restricted by convention (not DB constraint, since Group
  membership can change) to users in the "Sales Representative" or
  "Sales Manager" groups. See Client.sales_representative's help_text and
  masters.forms for the queryset filtering.
- CompanyInfo and DocumentSettings are both singletons (only one row is
  meant to ever exist). We enforce that softly via a get_solo() classmethod
  rather than a hard DB constraint, since a hard constraint would need a
  migration-time data decision; get_solo() creates the row on first access
  using COMPANY_DEFAULTS from settings.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from simple_history.models import HistoricalRecords

from core.models import AuditModel


class Currency(AuditModel):
    name = models.CharField(max_length=50)
    code = models.CharField(max_length=3, unique=True, help_text="ISO 4217 code, e.g. USD, KES, EUR")
    symbol = models.CharField(max_length=5, help_text="e.g. $, KSh, €")
    exchange_rate = models.DecimalField(
        max_digits=14, decimal_places=6, default=1,
        help_text="Rate relative to the base/reporting currency.",
    )
    is_active = models.BooleanField(default=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ["code"]
        verbose_name_plural = "Currencies"

    def __str__(self):
        return f"{self.code} ({self.symbol})"


class PaymentTerm(AuditModel):
    name = models.CharField(max_length=50, help_text="e.g. Cash, 7 Days, 30 Days, 60 Days")
    days = models.PositiveIntegerField(default=0, help_text="Number of days until payment is due.")
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ["days"]

    def __str__(self):
        return self.name


class Commodity(AuditModel):
    """The actual goods being transported (e.g. Flowers, Machinery, Electronics)."""
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    hs_code = models.CharField("HS Code", max_length=20, blank=True)
    is_active = models.BooleanField(default=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Commodities"

    def __str__(self):
        return self.name


class Port(AuditModel):
    class PortType(models.TextChoices):
        SEA = "sea", "Sea"
        AIR = "air", "Air"
        LAND = "land", "Land"

    name = models.CharField(max_length=150)
    code = models.CharField(max_length=10, blank=True, help_text="e.g. UNLOCODE, IATA/ICAO code")
    country = models.CharField(max_length=100)
    port_type = models.CharField(max_length=10, choices=PortType.choices)
    is_active = models.BooleanField(default=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ["country", "name"]
        unique_together = ("name", "country", "port_type")

    def __str__(self):
        return f"{self.name}, {self.country} ({self.get_port_type_display()})"


class Transporter(AuditModel):
    company_name = models.CharField(max_length=150)
    contact_person = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    vehicle_types = models.CharField(
        max_length=255, blank=True,
        help_text="Comma-separated, e.g. 'Flatbed, Reefer Truck, Low-bed Trailer'",
    )
    license_number = models.CharField(max_length=100, blank=True)
    license_expiry = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ["company_name"]

    def __str__(self):
        return self.company_name


class Supplier(AuditModel):
    class SupplierType(models.TextChoices):
        SHIPPING_LINE = "shipping_line", "Shipping Line"
        CLEARING_AGENT = "clearing_agent", "Clearing Agent"
        TRANSPORTER = "transporter", "Transporter"
        WAREHOUSE = "warehouse", "Warehouse / Storage"
        INSURANCE = "insurance", "Insurance"
        GENERAL = "general", "General Vendor"

    company_name = models.CharField(max_length=150)
    contact_person = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    tax_number = models.CharField(max_length=50, blank=True)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="suppliers")
    payment_terms = models.ForeignKey(PaymentTerm, on_delete=models.PROTECT, related_name="suppliers")
    supplier_type = models.CharField(max_length=20, choices=SupplierType.choices, default=SupplierType.GENERAL)
    is_active = models.BooleanField(default=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ["company_name"]

    def __str__(self):
        return self.company_name


class Item(AuditModel):
    """
    A billable service required to move a commodity (Freight, Transport,
    Handling, Storage, Customs clearance, Insurance, ...). VAT is set per
    item (not globally) because items can originate from different
    jurisdictions with different VAT treatment -- e.g. Air Freight at 0%
    alongside Handling/Storage at 16%.
    """

    class ItemType(models.TextChoices):
        FREIGHT = "freight", "Freight"
        TRANSPORT = "transport", "Transport"
        HANDLING = "handling", "Handling"
        STORAGE = "storage", "Storage"
        CUSTOMS_CLEARANCE = "customs_clearance", "Customs Clearance"
        INSURANCE = "insurance", "Insurance"
        OTHER = "other", "Other"

    name = models.CharField(max_length=150)
    code = models.CharField(
        max_length=30, blank=True,
        help_text="Short internal code/SKU, e.g. 'FRT-AIR-001'. Shown in the item dropdown for quick lookup.",
    )
    description = models.TextField(
        blank=True,
        help_text="Longer description auto-filled onto a quotation line when this item is selected "
                   "(falls back to the Name above if left blank).",
    )
    item_type = models.CharField(max_length=20, choices=ItemType.choices)
    supplier = models.ForeignKey(
        Supplier, on_delete=models.PROTECT, related_name="items",
        null=True, blank=True,
        help_text="The supplier this cost is sourced from, if applicable.",
    )
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="items")
    cost_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    selling_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    vat_applicable = models.BooleanField(default=True)
    vat_percentage = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="e.g. 16.00 for 16%. Set to 0 for zero-rated/exempt items such as Air Freight.",
    )
    is_active = models.BooleanField(default=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ["item_type", "name"]

    def __str__(self):
        label = f"{self.code} — {self.name}" if self.code else self.name
        return f"{label} ({self.get_item_type_display()})"

    def clean(self):
        if not self.vat_applicable and self.vat_percentage:
            raise ValidationError({"vat_percentage": "VAT percentage must be 0 when item is not VAT applicable."})

    @property
    def margin(self):
        return self.selling_price - self.cost_price


class Client(AuditModel):
    company_name = models.CharField(max_length=150)
    customer_code = models.CharField(max_length=20, unique=True, blank=True)
    contact_person = models.CharField(max_length=150, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    billing_address = models.TextField(blank=True)
    shipping_address = models.TextField(blank=True)
    tax_number = models.CharField(max_length=50, blank=True)

    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="clients")
    payment_terms = models.ForeignKey(PaymentTerm, on_delete=models.PROTECT, related_name="clients")
    sales_representative = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="clients",
        help_text="Should be a user in the Sales Representative or Sales Manager group.",
        limit_choices_to={"groups__name__in": ["Sales Representative", "Sales Manager"]},
    )
    is_active = models.BooleanField(default=True)
    history = HistoricalRecords()

    class Meta:
        ordering = ["company_name"]

    def __str__(self):
        return f"{self.company_name} ({self.customer_code})"

    def save(self, *args, **kwargs):
        if not self.customer_code:
            self.customer_code = self._generate_customer_code()
        super().save(*args, **kwargs)

    @staticmethod
    def _generate_customer_code():
        """
        Simple sequential CUS0001-style code. Master data creation is
        low-volume/low-concurrency (unlike transactional documents), so a
        locked count-based approach is sufficient here; document numbers
        (quotations, invoices, ...) use the stricter core.DocumentSequence
        instead.
        """
        with transaction.atomic():
            last = Client.objects.select_for_update().order_by("-id").first()
            next_id = (last.id + 1) if last else 1
            return f"CUS{str(next_id).zfill(4)}"

    def autofill_payload(self):
        """
        Returns the fields the quotation form should auto-populate when this
        client is selected, per the spec: currency, payment terms, sales
        rep, billing information. Consumed by masters/api.py.
        """
        return {
            "currency_id": self.currency_id,
            "currency_code": self.currency.code if self.currency_id else None,
            "payment_terms_id": self.payment_terms_id,
            "payment_terms_name": self.payment_terms.name if self.payment_terms_id else None,
            "sales_representative_id": self.sales_representative_id,
            "sales_representative_name": str(self.sales_representative) if self.sales_representative_id else None,
            "billing_address": self.billing_address or self.address,
        }


class ReferenceDocument(AuditModel):
    """
    An uploaded supporting file (client PO, customs paperwork, correspondence,
    etc.) that can be linked to a Quotation instead of typing a free-text
    reference number. Uploaded here first, then picked from a searchable
    dropdown on the quotation form -- and because it's linked (not just
    named), the file's own detail/usage page can show every quotation (and,
    through it, every proforma/invoice) that was ever linked to it, giving
    full traceability from a single supporting document to the whole
    downstream paper trail.
    """
    name = models.CharField(max_length=150, help_text="A short label, e.g. 'Client PO #4021' or 'Customs Form C63'.")
    file = models.FileField(upload_to="reference_documents/%Y/%m/")
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, help_text="Inactive documents are hidden from the selection dropdown but not deleted.")
    history = HistoricalRecords()

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Reference Document"
        verbose_name_plural = "Reference Documents"

    def __str__(self):
        return self.name


class CompanyInfo(AuditModel):
    """Singleton: the company's own details, used on every generated document."""
    name = models.CharField(max_length=150)
    tagline = models.CharField(max_length=150, blank=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    website = models.CharField(max_length=150, blank=True, help_text="e.g. www.example.com")
    tax_id = models.CharField(max_length=50, blank=True)
    logo = models.ImageField(upload_to="company/", null=True, blank=True)
    default_currency = models.ForeignKey(
        Currency, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    history = HistoricalRecords()

    class Meta:
        verbose_name = "Company Information"
        verbose_name_plural = "Company Information"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Enforce singleton softly: always reuse pk=1.
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass  # Singleton: never actually delete via the ORM/admin.

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={
            "name": settings.COMPANY_DEFAULTS.get("NAME", "Your Company Ltd"),
        })
        return obj


class DocumentSettings(AuditModel):
    """Singleton: numbering prefixes and boilerplate text for generated documents."""
    quotation_prefix = models.CharField(max_length=10, default="QT")
    proforma_prefix = models.CharField(max_length=10, default="PI")
    invoice_prefix = models.CharField(max_length=10, default="INV")
    receipt_prefix = models.CharField(max_length=10, default="RCPT")

    default_vat_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=16)
    quotation_validity_days = models.PositiveIntegerField(default=30)

    quotation_terms = models.TextField(
        blank=True, help_text="Default terms & conditions text printed on quotations.",
    )
    invoice_terms = models.TextField(blank=True)
    document_footer_note = models.CharField(max_length=255, blank=True)
    history = HistoricalRecords()

    class Meta:
        verbose_name = "Document Settings"
        verbose_name_plural = "Document Settings"

    def __str__(self):
        return "Document Settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
