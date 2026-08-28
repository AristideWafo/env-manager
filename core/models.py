"""
Data model — mirrors DATA_MODEL.md exactly. Do not add fields without updating
that spec first.
"""

import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    App auth is WebAuthn-only (see Credential below); `password` stays unusable
    for DEVELOPER accounts. `is_staff`/`is_superuser` remain available so an
    ADMIN can also use the Django admin site with a normal password if needed
    for break-glass/ops access — that is separate from the app's own login.
    """

    class Role(models.TextChoices):
        ADMIN = "ADMIN", "Admin"
        DEVELOPER = "DEVELOPER", "Developer"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=150)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.DEVELOPER)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    def __str__(self):
        return self.email

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN


class Credential(models.Model):
    """A registered WebAuthn authenticator (passkey) for a user."""

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        REVOKED = "REVOKED", "Revoked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="credentials")
    credential_id = models.BinaryField(unique=True)
    public_key = models.BinaryField()
    sign_count = models.BigIntegerField(default=0)
    device_label = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.device_label or self.id} ({self.user.email})"


class AllowedRoot(models.Model):
    """
    Filesystem roots an ADMIN has declared safe for .env writes. Every project
    path must resolve to a canonical descendant of one of these (path traversal
    / symlink-escape guard — see core/envfile.py).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    path = models.CharField(max_length=1024, unique=True)
    label = models.CharField(max_length=255)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.label} ({self.path})"


class Project(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    allowed_root = models.ForeignKey(AllowedRoot, on_delete=models.PROTECT, related_name="projects")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Environment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="environments")
    name = models.CharField(max_length=100)
    relative_path = models.CharField(max_length=1024)
    revision = models.IntegerField(default=0)
    locked_for_deploy = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "name"], name="uniq_project_env_name"),
        ]

    def __str__(self):
        return f"{self.project.name}/{self.name}"


class Variable(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    environment = models.ForeignKey(Environment, on_delete=models.CASCADE, related_name="variables")
    key = models.CharField(max_length=255)
    value = models.TextField(blank=True, default="")
    encrypted_value = models.BinaryField(null=True, blank=True)
    is_secret = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Structured-editor metadata (core/envdoc.py). group_name/leading_comment/
    # order DO feed the file write (envfile.render_document groups/comments
    # the output using exactly these fields) — but losing this metadata
    # never loses a value, only formatting: a file rewritten from scratch
    # falls back to one flat, ungrouped, uncommented block.
    # group_name membership must stay contiguous in `order` across all of an
    # environment's variables — see services._group_blocks and the
    # functions that maintain it (reorder_variables, swap_variable_order,
    # update_variable_layout, import's _normalize_group_contiguity).
    order = models.PositiveIntegerField(default=0)
    group_name = models.CharField(max_length=255, blank=True, default="")
    leading_comment = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["environment", "key"], name="uniq_env_var_key"),
        ]
        ordering = ["order"]

    def __str__(self):
        return f"{self.environment}:{self.key}"


class Permission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="permissions")
    environment = models.ForeignKey(Environment, on_delete=models.CASCADE, related_name="permissions")
    can_read = models.BooleanField(default=False)
    can_write = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "environment"], name="uniq_user_env_permission"),
        ]

    def __str__(self):
        return f"{self.user.email}@{self.environment} R{int(self.can_read)}W{int(self.can_write)}D{int(self.can_delete)}"


class Revision(models.Model):
    """Immutable snapshot created on every successful write. Never deleted."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    environment = models.ForeignKey(Environment, on_delete=models.CASCADE, related_name="revisions")
    revision_number = models.IntegerField()
    snapshot = models.JSONField()
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["environment", "revision_number"], name="uniq_env_revision_number"),
        ]
        ordering = ["-revision_number"]

    def __str__(self):
        return f"{self.environment} rev {self.revision_number}"


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = "CREATE", "Create"
        UPDATE = "UPDATE", "Update"
        DELETE = "DELETE", "Delete"
        LOCK = "LOCK", "Lock"
        UNLOCK = "UNLOCK", "Unlock"
        RESTORE = "RESTORE", "Restore"
        LOGIN = "LOGIN", "Login"
        REVEAL = "REVEAL", "Reveal"

    class Result(models.TextChoices):
        SUCCESS = "SUCCESS", "Success"
        FAILURE = "FAILURE", "Failure"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    environment = models.ForeignKey(Environment, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    action = models.CharField(max_length=20, choices=Action.choices)
    target = models.CharField(max_length=255, blank=True)
    result = models.CharField(max_length=10, choices=Result.choices)
    detail = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.created_at}] {self.action} {self.target} -> {self.result}"
