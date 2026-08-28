import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Create or update the production superuser."

    def handle(self, *args, **options):
        User = get_user_model()

        username = os.environ.get("DJANGO_ADMIN_USERNAME")
        email = os.environ.get("DJANGO_ADMIN_EMAIL", "")
        password = os.environ.get("DJANGO_ADMIN_PASSWORD")

        if not username:
            self.stdout.write(
                self.style.ERROR(
                    "DJANGO_ADMIN_USERNAME is not configured."
                )
            )
            return

        if not password:
            self.stdout.write(
                self.style.ERROR(
                    "DJANGO_ADMIN_PASSWORD is not configured."
                )
            )
            return

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
            },
        )

        user.email = email
        user.is_active = True
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()

        if created:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Superuser '{username}' created successfully."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"User '{username}' updated as superuser successfully."
                )
            )