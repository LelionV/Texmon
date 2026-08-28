from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.shortcuts import render
from django.views.generic import ListView

from .models import User


@login_required
def profile(request):
    return render(request, "accounts/profile.html", {"user_obj": request.user})


class UserListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """Admin-only list of ERP users, primarily for the Administrator role."""
    model = User
    permission_required = "accounts.view_user"
    template_name = "accounts/user_list.html"
    context_object_name = "users"
    paginate_by = 25

    def get_queryset(self):
        return User.objects.all().order_by("first_name", "last_name")

from django.contrib.auth import login
from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect
def register(request):
    """Create the first ERP user as the system administrator."""

    if User.objects.exists():
        messages.error(
            request,
            "Registration is disabled. Please contact an administrator.",
        )
        return redirect("accounts:login")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        password = request.POST.get("password", "")
        password_confirm = request.POST.get("password_confirm", "")

        if password != password_confirm:
            return render(
                request,
                "accounts/register.html",
                {"error": "Passwords do not match."},
            )

        if User.objects.filter(username=username).exists():
            return render(
                request,
                "accounts/register.html",
                {"error": "Username already exists."},
            )

        with transaction.atomic():
            user = User.objects.create_user(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                password=password,
            )

            user.is_active = True
            user.is_staff = True
            user.is_superuser = True
            user.save()

        login(request, user)

        messages.success(
            request,
            "Administrator account created successfully.",
        )

        return redirect("dashboard")

    return render(request, "accounts/register.html")