"""
Cross-cutting models shared by every business app.

AuditModel
----------
Every important transactional model (Quotation, Proforma, Invoice, Payment,
Expense, ...) should inherit from this instead of models.Model directly. It
gives us created_by/updated_by/created_at/updated_at for free and a
consistent way to know "who touched this record last".

created_by/updated_by are set by the service layer / views (via
core.utils.get_current_user() which reads the thread-local set by
CurrentUserMiddleware) rather than here, because plain model save() has no
reliable access to the request user. See core/middleware.py and
core/utils.py.

DocumentSequence
-----------------
Generates gapless-per-year sequential document numbers in the form
PREFIX-YYYY-0001 (e.g. QT-2026-0001, PI-2026-0001, INV-2026-0001,
RCPT-2026-0001). One row per (prefix, year); `last_number` is incremented
inside a select_for_update() transaction so concurrent requests can't
collide.
"""

from django.conf import settings
from django.db import models, transaction


class AuditModel(models.Model):
    """Abstract base providing created/updated audit fields."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(app_label)s_%(class)s_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(app_label)s_%(class)s_updated",
    )

    class Meta:
        abstract = True


class DocumentSequence(models.Model):
    """
    Tracks the last-used running number for a document prefix within a
    given year, e.g. ('QT', 2026) -> 7 means QT-2026-0007 was last issued.
    """

    prefix = models.CharField(max_length=10)
    year = models.PositiveIntegerField()
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ("prefix", "year")
        verbose_name = "Document Sequence"
        verbose_name_plural = "Document Sequences"

    def __str__(self):
        return f"{self.prefix}-{self.year}: {self.last_number}"

    @classmethod
    def next_number(cls, prefix: str, year: int, padding: int = 4) -> str:
        """
        Atomically claim and return the next formatted document number for
        `prefix` in `year`, e.g. next_number('QT', 2026) -> 'QT-2026-0001'.
        """
        with transaction.atomic():
            seq, _ = cls.objects.select_for_update().get_or_create(
                prefix=prefix, year=year
            )
            seq.last_number += 1
            seq.save(update_fields=["last_number"])
            return f"{prefix}-{year}-{str(seq.last_number).zfill(padding)}"
