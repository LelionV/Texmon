"""
accounts app: authentication, roles and activity auditing.

User
----
Extends AbstractUser instead of composing a separate Profile model. Rationale:
almost every permission check and every FK across the whole ERP (sales rep on
a Client, created_by on a Quotation, approved_by on an Expense, ...) needs to
point at "the user", and role membership itself is expressed through Django's
built-in Group model (per the spec's explicit "Use Django Groups" requirement)
rather than a custom `role` field. A profile-only approach would force every
such FK through an extra join for no benefit.

We do add a small number of fields Django's default User lacks but that this
ERP needs everywhere (phone, a soft-disable `is_active_employee` distinct
from Django's login-gating `is_active`, and a department/job_title pair used
for display and future workflow routing).

UserActivityLog
----------------
A generic, append-only log of significant user actions (login, logout,
create/update/approve/lock on any tracked model). Kept intentionally simple
(a free-text action + optional generic FK to the affected object) so every
app can log to it without a hard dependency on that app's models.
"""

from django.contrib.auth.models import AbstractUser
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class User(AbstractUser):
    phone = models.CharField(max_length=30, blank=True)
    department = models.CharField(max_length=100, blank=True)
    job_title = models.CharField(max_length=100, blank=True)
    is_active_employee = models.BooleanField(
        default=True,
        help_text="Distinct from 'is_active' (login access). "
                  "An employee can be off-boarded here while keeping historical "
                  "records intact, before separately disabling login access.",
    )

    class Meta:
        ordering = ["first_name", "last_name"]

    def __str__(self):
        full = self.get_full_name()
        return full or self.username

    @property
    def role_names(self):
        """Convenience: list of Group names this user belongs to."""
        return list(self.groups.values_list("name", flat=True))


class UserActivityLog(models.Model):
    class Action(models.TextChoices):
        LOGIN = "login", "Login"
        LOGOUT = "logout", "Logout"
        CREATE = "create", "Create"
        UPDATE = "update", "Update"
        DELETE = "delete", "Delete"
        SUBMIT = "submit", "Submit"
        APPROVE = "approve", "Approve"
        REJECT = "reject", "Reject"
        CONVERT = "convert", "Convert"
        LOCK = "lock", "Lock"
        PRINT = "print", "Print / Download"
        PAYMENT = "payment", "Payment Recorded"
        OTHER = "other", "Other"

    user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="activity_logs",
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    description = models.CharField(max_length=255, blank=True)

    # Optional link to the object the action was performed on.
    content_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.SET_NULL
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "User Activity Log"
        verbose_name_plural = "User Activity Logs"

    def __str__(self):
        return f"{self.user} - {self.get_action_display()} @ {self.created_at:%Y-%m-%d %H:%M}"

    @classmethod
    def log(cls, user, action, description="", obj=None, request=None):
        """Convenience creator used throughout the codebase, e.g.
        UserActivityLog.log(request.user, UserActivityLog.Action.APPROVE,
                             f"Approved {quotation}", obj=quotation, request=request)
        """
        ip = None
        if request is not None:
            ip = request.META.get("REMOTE_ADDR")
        return cls.objects.create(
            user=user,
            action=action,
            description=description,
            content_type=ContentType.objects.get_for_model(obj) if obj else None,
            object_id=obj.pk if obj else None,
            ip_address=ip,
        )
