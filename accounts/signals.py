"""
Wire Django's built-in auth signals into UserActivityLog so every login/
logout is captured automatically without touching the view layer (works
whether the login happens via the Django admin or the app's own login view).
"""

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver

from .models import UserActivityLog


@receiver(user_logged_in)
def log_user_logged_in(sender, request, user, **kwargs):
    UserActivityLog.log(user, UserActivityLog.Action.LOGIN, "User logged in", request=request)


@receiver(user_logged_out)
def log_user_logged_out(sender, request, user, **kwargs):
    if user is not None:
        UserActivityLog.log(user, UserActivityLog.Action.LOGOUT, "User logged out", request=request)
