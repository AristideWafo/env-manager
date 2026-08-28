from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.urls import reverse

from .models import (
    AllowedRoot,
    AuditLog,
    Credential,
    Environment,
    Permission,
    Project,
    Revision,
    User,
    Variable,
)
from .webauthn_service import make_invitation_token


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("email", "display_name", "role", "is_active", "is_staff")
    ordering = ("email",)
    fieldsets = DjangoUserAdmin.fieldsets + (("Env Manager", {"fields": ("role", "display_name")}),)
    actions = ["generate_invitation_link"]

    @admin.action(description="Generate passkey invitation link (UC-03/UC-05)")
    def generate_invitation_link(self, request, queryset):
        for user in queryset:
            token = make_invitation_token(user)
            # reverse() (not a hardcoded "/register/") so the URL comes out
            # script-prefixed too when the app is mounted under a path via
            # DJANGO_FORCE_SCRIPT_NAME (e.g. behind a reverse-proxy PathPrefix).
            path = reverse("core:register")
            url = request.build_absolute_uri(f"{path}?token={token}")
            self.message_user(request, f"{user.email}: {url}", level=messages.INFO)


@admin.register(Credential)
class CredentialAdmin(admin.ModelAdmin):
    list_display = ("user", "device_label", "status", "created_at", "last_used_at")
    list_filter = ("status",)


@admin.register(AllowedRoot)
class AllowedRootAdmin(admin.ModelAdmin):
    list_display = ("label", "path", "created_by", "created_at")


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "allowed_root", "created_at")


@admin.register(Environment)
class EnvironmentAdmin(admin.ModelAdmin):
    list_display = ("project", "name", "relative_path", "revision", "locked_for_deploy")
    list_filter = ("locked_for_deploy",)


@admin.register(Variable)
class VariableAdmin(admin.ModelAdmin):
    list_display = ("environment", "key", "is_secret", "updated_at")
    list_filter = ("is_secret",)

    def get_readonly_fields(self, request, obj=None):
        # Never let admin edit encrypted_value/value directly out of band —
        # writes must go through the API so revision/audit stay consistent.
        return ("value", "encrypted_value", "created_at", "updated_at")


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ("user", "environment", "can_read", "can_write", "can_delete")


@admin.register(Revision)
class RevisionAdmin(admin.ModelAdmin):
    list_display = ("environment", "revision_number", "created_by", "created_at")

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "target", "result")
    list_filter = ("action", "result")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
