"""
Wires the accounting ledger to the invoicing app's models via signals,
rather than having invoicing import/call into accounting directly. This
keeps the dependency one-directional (accounting depends on invoicing,
never the reverse) while still guaranteeing every Invoice and every
Payment produces exactly one LedgerEntry automatically, with no risk of a
view forgetting to post one manually.

Invoice posting listens to invoicing.models.invoice_finalized rather than
post_save: a plain post_save fires the moment Invoice.save() is first
called inside create_from_proforma, which is *before* line items are
copied over and recalculate_totals() runs -- at that point grand_total is
still 0, which would post a worthless 0.00 debit. invoice_finalized is
sent explicitly once the invoice's totals are final.

Payment posting listens to post_save directly: a Payment's `amount` is
already fully set before save() is called (no post-save recalculation
step), so post_save's timing is fine there.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from invoicing.models import Payment, invoice_finalized
from .models import LedgerEntry


@receiver(invoice_finalized)
def post_invoice_to_ledger(sender, invoice, **kwargs):
    LedgerEntry.post_invoice(invoice, user=invoice.created_by)


@receiver(post_save, sender=Payment)
def post_payment_to_ledger(sender, instance, created, **kwargs):
    if created:
        LedgerEntry.post_payment(instance, user=instance.created_by)
