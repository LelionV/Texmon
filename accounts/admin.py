from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User, UserActivityLog


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = (
        "username", "get_full_name", "email", "department", "job_title",
        "is_active", "is_active_employee", "is_staff",
    )
    list_filter = ("is_active", "is_active_employee", "is_staff", "groups")
    search_fields = ("username", "first_name", "last_name", "email", "department")

    fieldsets = DjangoUserAdmin.fieldsets + (
        ("ERP Profile", {
            "fields": ("phone", "department", "job_title", "is_active_employee"),
        }),
    )

    @admin.display(description="Full name")
    def get_full_name(self, obj):
        return obj.get_full_name()


@admin.register(UserActivityLog)
class UserActivityLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "description", "content_type", "object_id", "ip_address")
    list_filter = ("action", "created_at")
    search_fields = ("description", "user__username")
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in UserActivityLog._meta.fields]

    def has_add_permission(self, request):
        # Activity log is system-generated only.
        return False

    def has_change_permission(self, request, obj=None):
        return False
