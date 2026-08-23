"""
accounting app: a running per-client Ledger, and Statement of Account
generation from it.

Design notes
------------
- LedgerEntry is the single source of truth for "what does this client owe
  us and when did that change". Rather than having the Statement of Account
  re-derive balances by separately querying Invoice and Payment tables (and
  risking the two falling out of sync with different rounding/filtering
  logic), every Invoice creation and every Payment automatically writes one
  LedgerEntry each (a debit for the invoice, a credit for the payment) via
  signal receivers in accounting/signals.py listening to the invoicing
  app's models. This keeps invoicing free of any dependency on accounting
  (signals are wired from the accounting side), while accounting has one
  simple, append-only table to build every report from.
- `running_balance` is computed and stored at write time inside a
  `select_for_update()`-locked transaction (same defensive pattern as
  Payment/SupplierPayment elsewhere), so it can never be recomputed
  incorrectly later and concurrent postings for the same client can't race.
  LedgerEntry rows are otherwise immutable -- there's no update/delete path
  in the UI, mirroring how a real accounting ledger works.
- StatementOfAccount is a lightweight, persisted *header* (statement
  number, client, period, opening/closing balance, who generated it and
  when) for audit/reference -- per the spec's "Generate customer statements
  from Invoices, Payments, Receipts" -- but does NOT duplicate the line
  items into its own table. `StatementOfAccount.get_lines()` re-queries
  LedgerEntry for the stored period on demand. Ledger entries are
  immutable, so this is safe and avoids a second copy of the same data
  drifting out of sync.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from core.models import AuditModel, DocumentSequence
from masters.models import Client


class LedgerEntry(models.Model):
    class EntryType(models.TextChoices):
        INVOICE = "invoice", "Invoice"
        PAYMENT = "payment", "Payment"
        ADJUSTMENT = "adjustment", "Adjustment"

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="ledger_entries")
    entry_type = models.CharField(max_length=15, choices=EntryType.choices)
    date = models.DateField(default=timezone.localdate)
    reference_number = models.CharField(max_length=50, blank=True)
    description = models.CharField(max_length=255, blank=True)

    debit = models.DecimalField(max_digits=14, decimal_places=2, default=0, help_text="Amount the client now owes (e.g. an invoice).")
    credit = models.DecimalField(max_digits=14, decimal_places=2, default=0, help_text="Amount reducing what the client owes (e.g. a payment).")
    running_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    invoice = models.ForeignKey("invoicing.Invoice", on_delete=models.SET_NULL, null=True, blank=True, related_name="ledger_entries")
    payment = models.ForeignKey("invoicing.Payment", on_delete=models.SET_NULL, null=True, blank=True, related_name="ledger_entries")

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ["client", "date", "id"]
        verbose_name_plural = "Ledger Entries"
        permissions = []

    def __str__(self):
        return f"{self.client} - {self.get_entry_type_display()} - {self.date}"

    @classmethod
    def _post(cls, *, client, entry_type, date, reference_number, description,
              debit=Decimal("0.00"), credit=Decimal("0.00"), invoice=None, payment=None, user=None):
        """Atomically append a ledger entry for `client`, computing the new
        running balance from the client's last posted entry under a lock so
        two concurrent postings (e.g. an invoice and a payment landing at
        the same instant) can never compute the same stale balance."""
        with transaction.atomic():
            last = (
                cls.objects.select_for_update()
                .filter(client=client)
                .order_by("-date", "-id")
                .first()
            )
            previous_balance = last.running_balance if last else Decimal("0.00")
            new_balance = previous_balance + debit - credit
            return cls.objects.create(
                client=client, entry_type=entry_type, date=date,
                reference_number=reference_number, description=description,
                debit=debit, credit=credit, running_balance=new_balance,
                invoice=invoice, payment=payment, created_by=user,
            )

    @classmethod
    def post_invoice(cls, invoice, user=None):
        return cls._post(
            client=invoice.client, entry_type=cls.EntryType.INVOICE, date=invoice.date,
            reference_number=invoice.invoice_number,
            description=f"Invoice {invoice.invoice_number}",
            debit=invoice.grand_total, invoice=invoice, user=user,
        )

    @classmethod
    def post_payment(cls, payment, user=None):
        invoice = payment.invoice
        return cls._post(
            client=invoice.client, entry_type=cls.EntryType.PAYMENT, date=payment.payment_date,
            reference_number=payment.reference_number or invoice.invoice_number,
            description=f"Payment received - {invoice.invoice_number}",
            credit=payment.amount, invoice=invoice, payment=payment, user=user,
        )


class StatementOfAccount(AuditModel):
    statement_number = models.CharField(max_length=30, unique=True, blank=True)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="statements")
    date_from = models.DateField()
    date_to = models.DateField()
    opening_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    closing_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ["-date_to", "-id"]

    def __str__(self):
        return self.statement_number or f"Statement #{self.pk}"

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse("accounting:statement_detail", args=[self.pk])

    def save(self, *args, **kwargs):
        if not self.statement_number:
            year = self.date_to.year if self.date_to else timezone.localdate().year
            self.statement_number = DocumentSequence.next_number("STMT", year)
        super().save(*args, **kwargs)

    def get_lines(self):
        """Live-queries the immutable ledger for this statement's stored
        client/period -- see the module docstring for why this isn't
        duplicated into its own table."""
        return LedgerEntry.objects.filter(
            client=self.client, date__gte=self.date_from, date__lte=self.date_to,
        ).order_by("date", "id")

    @classmethod
    def generate(cls, client, date_from, date_to, user=None):
        """The only supported way to create a StatementOfAccount. Computes
        the opening balance from the client's last ledger entry strictly
        before `date_from`, and the closing balance from the last entry at
        or before `date_to` (defaulting both to the running balance, or 0
        if the client has no ledger history yet)."""
        opening_entry = (
            LedgerEntry.objects.filter(client=client, date__lt=date_from)
            .order_by("-date", "-id").first()
        )
        opening_balance = opening_entry.running_balance if opening_entry else Decimal("0.00")

        closing_entry = (
            LedgerEntry.objects.filter(client=client, date__lte=date_to)
            .order_by("-date", "-id").first()
        )
        closing_balance = closing_entry.running_balance if closing_entry else opening_balance

        statement = cls.objects.create(
            client=client, date_from=date_from, date_to=date_to,
            opening_balance=opening_balance, closing_balance=closing_balance,
            created_by=user, updated_by=user,
        )
        return statement
