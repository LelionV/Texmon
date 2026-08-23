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
