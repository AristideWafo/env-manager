"""
Cross-cutting business rules: encryption, permission checks, audit logging,
and the optimistic-locked revision write path. API views should not touch the
models' write paths directly for Variable/Revision/AuditLog — go through here
so every rule in AGENT_CONTEXT.md §8 is enforced in one place.
"""

from __future__ import annotations

import logging
import re

from cryptography.fernet import Fernet
from django.conf import settings
from django.db import transaction

from . import envdoc
from .envfile import PathNotAllowed, read_environment_file, write_environment_file
from .models import AuditLog, Environment, Permission, Revision, Variable

logger = logging.getLogger(__name__)

# .env-compatible key: what a POSIX shell / dotenv parser accepts unquoted on
# the left of "=". Enforced at write time (UC-20) so a bad key can never
# reach the file the CI/CD pipeline reads.
KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def validate_key(key: str) -> None:
    if not key or not KEY_RE.match(key):
        raise ValidationError(
            f"invalid variable key {key!r}: must match {KEY_RE.pattern}"
        )


class ApiError(Exception):
    """Carries (code, http_status, message) for the Ninja error envelope."""

    def __init__(self, code: str, status: int, message: str):
        self.code = code
        self.status = status
        self.message = message
        super().__init__(message)


class RevisionConflict(ApiError):
    def __init__(self, message="revision provided is stale"):
        super().__init__("REVISION_CONFLICT", 409, message)


class EnvironmentLocked(ApiError):
    def __init__(self, message="environment is locked for deploy"):
        super().__init__("ENVIRONMENT_LOCKED", 423, message)


class Forbidden(ApiError):
    def __init__(self, message="insufficient permission"):
        super().__init__("FORBIDDEN", 403, message)


class ValidationError(ApiError):
    def __init__(self, message="invalid payload"):
        super().__init__("VALIDATION_ERROR", 422, message)


class PathNotAllowedError(ApiError):
    def __init__(self, message="path outside allowed roots"):
        super().__init__("PATH_NOT_ALLOWED", 422, message)


class FilesystemError(ApiError):
    def __init__(self, message="failed to write .env file"):
        super().__init__("FILESYSTEM_ERROR", 500, message)


class NotFound(ApiError):
    def __init__(self, message="resource not found"):
        super().__init__("NOT_FOUND", 404, message)


# --- Crypto ------------------------------------------------------------------

def _fernet() -> Fernet:
    return Fernet(settings.FERNET_KEY.encode() if isinstance(settings.FERNET_KEY, str) else settings.FERNET_KEY)


def encrypt_value(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode())


def decrypt_value(ciphertext: bytes | None) -> str:
    # Defensive: a row can only reach encrypted_value=None with is_secret=True
    # via direct ORM/admin access, never through this module's write paths —
    # but if it happens, treat it as empty rather than crashing every future
    # write to the environment.
    if not ciphertext:
        return ""
    return _fernet().decrypt(bytes(ciphertext)).decode()


# --- Permissions ---------------------------------------------------------

def check_permission(user, environment: Environment, need: str) -> None:
    """need is one of 'read', 'write', 'delete'."""
    if getattr(user, "is_admin", False):
        return
    perm = Permission.objects.filter(user=user, environment=environment).first()
    if not perm or not getattr(perm, f"can_{need}"):
        logger.warning("permission denied: user=%s need=%s environment=%s", user, need, environment.id)
        raise Forbidden(f"missing {need} permission on this environment")


def visible_environments(user, queryset):
    if getattr(user, "is_admin", False):
        return queryset
    return queryset.filter(permissions__user=user).distinct()


# --- Audit -----------------------------------------------------------------

def audit(*, user, action: str, target: str = "", result: str = AuditLog.Result.SUCCESS,
          project=None, environment=None, detail: str | None = None) -> None:
    """
    Never pass a variable's value/encrypted_value in `detail` or `target`
    (AGENT_CONTEXT.md rule #3 / DATA_MODEL.md AuditLog notes).
    """
    AuditLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        project=project,
        environment=environment,
        action=action,
        target=target,
        result=result,
        detail=detail,
    )


# --- Variable serialization (secret masking) --------------------------------

def serialize_variable(var: Variable) -> dict:
    return {
        "key": var.key,
        "value": None if var.is_secret else var.value,
        "secret": var.is_secret,
        "updated_at": var.updated_at.isoformat(),
        "group": var.group_name,
        "comment": var.leading_comment,
        "order": var.order,
    }


def _next_order(environment: Environment) -> int:
    return (environment.variables.order_by("-order").values_list("order", flat=True).first() or 0) + 1


def _snapshot(environment: Environment) -> list[dict]:
    snap = []
    for var in environment.variables.all().order_by("key"):
        snap.append({
            "key": var.key,
            "value": var.value if not var.is_secret else None,
            "encrypted_value": var.encrypted_value.hex() if var.encrypted_value else None,
            "is_secret": var.is_secret,
            "order": var.order,
            "group_name": var.group_name,
            "leading_comment": var.leading_comment,
        })
    return snap


def _decrypted_variables_for_file(environment: Environment) -> list[dict]:
    out = []
    for var in environment.variables.all().order_by("key"):
        value = decrypt_value(var.encrypted_value) if var.is_secret else var.value
        out.append({"key": var.key, "value": value})
    return out


@transaction.atomic
def apply_batch(*, environment_id, user, revision: int, operations: list[dict]) -> Environment:
    """
    All-or-nothing batch write (UC-18): validate the whole batch, bump
    revision exactly once, snapshot, write the .env file, audit each op.
    Locks the Environment row for the duration (select_for_update) so two
    concurrent batches can't both pass the revision check.
    """
    environment = Environment.objects.select_for_update().get(pk=environment_id)

    if environment.locked_for_deploy:
        raise EnvironmentLocked()
    if environment.revision != revision:
        raise RevisionConflict()

    seen_keys_this_batch = set()
    existing = {v.key: v for v in environment.variables.all()}

    # Validate the entire batch before any write (UC-20 doubles as
    # UC-18's "all-or-nothing" requirement).
    for op in operations:
        action = op.get("op")
        key = op.get("key")
        if not key or action not in ("create", "update", "delete"):
            raise ValidationError(f"invalid operation: {op}")
        if key in seen_keys_this_batch:
            raise ValidationError(f"duplicate key in batch: {key}")
        seen_keys_this_batch.add(key)

        if action == "create":
            validate_key(key)
            if key in existing:
                raise ValidationError(f"variable already exists: {key}")
        elif action == "update":
            if key not in existing:
                raise ValidationError(f"variable not found: {key}")
        elif action == "delete":
            if key not in existing:
                raise ValidationError(f"variable not found: {key}")

    next_order = _next_order(environment)
    for op in operations:
        action, key = op["op"], op["key"]
        if action == "create":
            var = Variable(environment=environment, key=key, is_secret=bool(op.get("is_secret")), order=next_order)
            next_order += 1
            _set_value(var, op.get("value", ""), var.is_secret)
            var.save()
            audit(user=user, action=AuditLog.Action.CREATE, target=key,
                  project=environment.project, environment=environment)
        elif action == "update":
            var = existing[key]
            _set_value(var, op.get("value", ""), var.is_secret)
            var.save()
            audit(user=user, action=AuditLog.Action.UPDATE, target=key,
                  project=environment.project, environment=environment)
        elif action == "delete":
            existing[key].delete()
            audit(user=user, action=AuditLog.Action.DELETE, target=key,
                  project=environment.project, environment=environment)

    _bump_revision_and_write(environment, user)
    return environment


def _set_value(var: Variable, plaintext: str, is_secret: bool) -> None:
    if is_secret:
        var.value = ""
        var.encrypted_value = encrypt_value(plaintext)
    else:
        var.value = plaintext
        var.encrypted_value = None


def _bump_revision_and_write(environment: Environment, user) -> Revision:
    environment.revision += 1
    environment.save(update_fields=["revision"])
    revision = Revision.objects.create(
        environment=environment,
        revision_number=environment.revision,
        snapshot=_snapshot(environment),
        created_by=user if getattr(user, "is_authenticated", False) else None,
    )
    try:
        write_environment_file(environment, _decrypted_variables_for_file(environment))
    except PathNotAllowed as e:
        logger.error("path not allowed writing environment %s: %s", environment.id, e)
        raise PathNotAllowedError(str(e)) from e
    except OSError as e:
        logger.error("filesystem error writing environment %s: %s", environment.id, e)
        raise FilesystemError(f"could not write .env file: {e}") from e
    return revision


@transaction.atomic
def create_variable(*, environment_id, user, key, value, is_secret) -> Variable:
    environment = Environment.objects.select_for_update().get(pk=environment_id)
    if environment.locked_for_deploy:
        raise EnvironmentLocked()
    validate_key(key)
    if Variable.objects.filter(environment=environment, key=key).exists():
        raise ValidationError(f"variable already exists: {key}")
    var = Variable(environment=environment, key=key, is_secret=is_secret, order=_next_order(environment))
    _set_value(var, value, is_secret)
    var.save()
    _bump_revision_and_write(environment, user)
    audit(user=user, action=AuditLog.Action.CREATE, target=key,
          project=environment.project, environment=environment)
    logger.info("variable created: key=%s environment=%s user=%s", key, environment.id, user)
    return var


@transaction.atomic
def update_variable(*, environment_id, user, key, value, revision, is_secret=None) -> Variable:
    """is_secret=None keeps the current flag; pass True/False to flip it
    (UC-19 — marking an existing variable secret, or un-marking it)."""
    environment = Environment.objects.select_for_update().get(pk=environment_id)
    if environment.locked_for_deploy:
        raise EnvironmentLocked()
    if environment.revision != revision:
        raise RevisionConflict()
    try:
        var = Variable.objects.get(environment=environment, key=key)
    except Variable.DoesNotExist:
        raise NotFound(f"variable not found: {key}")
    _set_value(var, value, var.is_secret if is_secret is None else is_secret)
    var.is_secret = var.is_secret if is_secret is None else is_secret
    var.save()
    _bump_revision_and_write(environment, user)
    audit(user=user, action=AuditLog.Action.UPDATE, target=key,
          project=environment.project, environment=environment)
    logger.info("variable updated: key=%s environment=%s user=%s", key, environment.id, user)
    return var


@transaction.atomic
def delete_variable(*, environment_id, user, key, revision) -> None:
    environment = Environment.objects.select_for_update().get(pk=environment_id)
    if environment.locked_for_deploy:
        raise EnvironmentLocked()
    if environment.revision != revision:
        raise RevisionConflict()
    try:
        var = Variable.objects.get(environment=environment, key=key)
    except Variable.DoesNotExist:
        raise NotFound(f"variable not found: {key}")
    var.delete()
    _bump_revision_and_write(environment, user)
    audit(user=user, action=AuditLog.Action.DELETE, target=key,
          project=environment.project, environment=environment)
    logger.info("variable deleted: key=%s environment=%s user=%s", key, environment.id, user)


@transaction.atomic
def update_variable_layout(*, environment_id, user, key, group_name=None, leading_comment=None) -> Variable:
    """Structured-editor metadata only (core/envdoc.py concepts: which group a
    variable displays under, its leading comment). Never touches
    value/encrypted_value, never bumps the revision, never rewrites the file
    — write_environment_file's canonical always-quoted/alphabetical output
    doesn't consult these fields (see models.py). Allowed even when the
    environment is locked_for_deploy, since it can't change what's deployed.
    Pass None (the default) to leave a field unchanged."""
    environment = Environment.objects.get(pk=environment_id)
    try:
        var = Variable.objects.get(environment=environment, key=key)
    except Variable.DoesNotExist:
        raise NotFound(f"variable not found: {key}")
    update_fields = []
    if group_name is not None:
        var.group_name = group_name
        update_fields.append("group_name")
    if leading_comment is not None:
        var.leading_comment = leading_comment
        update_fields.append("leading_comment")
    if update_fields:
        var.save(update_fields=update_fields)
    audit(user=user, action=AuditLog.Action.UPDATE, target=f"layout:{key}",
          project=environment.project, environment=environment)
    return var


@transaction.atomic
def reorder_variables(*, environment_id, user, ordered_keys: list[str]) -> None:
    """Reassigns display order (0..N-1) to match ordered_keys exactly.
    Metadata-only — see update_variable_layout. ordered_keys must be exactly
    the environment's current variable keys, each once; a partial or stale
    list is rejected rather than silently reordering a subset."""
    environment = Environment.objects.select_for_update().get(pk=environment_id)
    existing = {v.key: v for v in environment.variables.all()}
    if sorted(ordered_keys) != sorted(existing.keys()) or len(ordered_keys) != len(set(ordered_keys)):
        raise ValidationError(
            "ordered_keys must contain exactly the environment's current variable keys, each once"
        )
    for i, key in enumerate(ordered_keys):
        var = existing[key]
        if var.order != i:
            var.order = i
            var.save(update_fields=["order"])
    audit(user=user, action=AuditLog.Action.UPDATE, target="reorder",
          project=environment.project, environment=environment)


def swap_variable_order(*, environment_id, user, key, direction: str) -> None:
    """Moves one variable one slot up/down in display order by swapping it
    with its immediate neighbor. A thin, UI-friendly wrapper around
    reorder_variables (no separate 'group move' concept — see DATA_MODEL.md:
    group is just Variable.group_name, so moving a variable across the group
    boundary at its neighbor also changes which group it displays under)."""
    if direction not in ("up", "down"):
        raise ValidationError(f"invalid direction: {direction!r} (must be 'up' or 'down')")
    environment = Environment.objects.select_for_update().get(pk=environment_id)
    keys = list(environment.variables.order_by("order").values_list("key", flat=True))
    if key not in keys:
        raise NotFound(f"variable not found: {key}")
    i = keys.index(key)
    j = i - 1 if direction == "up" else i + 1
    if 0 <= j < len(keys):
        keys[i], keys[j] = keys[j], keys[i]
        reorder_variables(environment_id=environment_id, user=user, ordered_keys=keys)


@transaction.atomic
def rename_group(*, environment_id, user, old_name, new_name) -> int:
    """Bulk-renames a group by updating group_name on every variable
    currently in it. There's no separate Group row to rename (see
    DATA_MODEL.md) — a group only exists as long as at least one variable
    references its name. Metadata-only: no revision bump, no file rewrite,
    allowed while locked. Returns the number of variables updated."""
    if not new_name.strip():
        raise ValidationError("new group name cannot be empty")
    environment = Environment.objects.select_for_update().get(pk=environment_id)
    updated = environment.variables.filter(group_name=old_name).update(group_name=new_name)
    if updated:
        audit(user=user, action=AuditLog.Action.UPDATE, target=f"rename_group:{old_name}->{new_name}",
              project=environment.project, environment=environment)
    return updated


@transaction.atomic
def ungroup(*, environment_id, user, group_name) -> int:
    """Removes every variable in group_name from display grouping
    (group_name -> ""), i.e. 'delete this group, keep its variables' —
    per envdoc.py's delete_group(keep_children=True) semantics. There's
    nothing else to delete since a group is just a shared group_name value.
    Returns the number of variables updated."""
    environment = Environment.objects.select_for_update().get(pk=environment_id)
    updated = environment.variables.filter(group_name=group_name).update(group_name="")
    if updated:
        audit(user=user, action=AuditLog.Action.UPDATE, target=f"ungroup:{group_name}",
              project=environment.project, environment=environment)
    return updated


def _leading_comment_for(container, index: int) -> str:
    """Text of the contiguous run of Comment siblings immediately preceding
    index in container.children (no Blank/other node between them and the
    variable). Joined with newlines; '' if none."""
    lines = []
    i = index - 1
    while i >= 0 and isinstance(container.children[i], envdoc.Comment):
        lines.append(container.children[i].text)
        i -= 1
    return "\n".join(reversed(lines))


@transaction.atomic
def import_variables_from_file(*, environment_id, user) -> int:
    """Populate untracked Variable rows from what's already on disk for this
    environment's .env file (e.g. an existing file that predates this
    environment being declared in the app). Keys already tracked in the DB
    are left untouched — this only fills gaps, never overwrites. Does not
    bump the revision or rewrite the file, since its content already matches.

    Uses core/envdoc.py to understand the real .env dialect (comments,
    groups, unquoted values) rather than only the app's own always-quoted
    canonical format, so a genuine legacy file imports correctly. The parsed
    group/leading-comment/order are stored on Variable as display metadata
    only (see models.py) — they never affect what write_environment_file
    puts on disk (still always-quoted/alphabetical, per envfile.py).

    Returns the number of variables imported."""
    environment = Environment.objects.select_for_update().get(pk=environment_id)
    try:
        content = read_environment_file(environment)
    except PathNotAllowed as e:
        logger.error("path not allowed importing environment %s: %s", environment.id, e)
        raise PathNotAllowedError(str(e)) from e
    except OSError as e:
        logger.error("filesystem error importing environment %s: %s", environment.id, e)
        raise FilesystemError(f"could not read .env file: {e}") from e
    if not content:
        return 0
    existing_keys = set(environment.variables.values_list("key", flat=True))
    next_order = _next_order(environment)
    imported = 0
    document = envdoc.parse(content)
    for container, index, entry in document.all_variables():
        if entry.key in existing_keys:
            continue
        group_name = container.name if isinstance(container, envdoc.Group) else ""
        var = Variable(
            environment=environment, key=entry.key, is_secret=False,
            group_name=group_name, leading_comment=_leading_comment_for(container, index),
            order=next_order,
        )
        _set_value(var, entry.value, False)
        var.save()
        existing_keys.add(entry.key)
        next_order += 1
        imported += 1
    if imported:
        audit(user=user, action=AuditLog.Action.CREATE, target=f"import:{imported} variable(s)",
              project=environment.project, environment=environment)
        logger.info("imported %d variable(s) from existing .env file into environment %s", imported, environment.id)
    return imported


@transaction.atomic
def restore_revision(*, environment_id, user, revision_number) -> Environment:
    """UC-26: restore creates a NEW revision from the old snapshot (never
    rewinds history — Revision rows are immutable, per DATA_MODEL.md)."""
    environment = Environment.objects.select_for_update().get(pk=environment_id)
    if environment.locked_for_deploy:
        raise EnvironmentLocked()
    try:
        target = Revision.objects.get(environment=environment, revision_number=revision_number)
    except Revision.DoesNotExist:
        raise NotFound(f"revision not found: {revision_number}")

    Variable.objects.filter(environment=environment).delete()
    for entry in target.snapshot:
        var = Variable(
            environment=environment, key=entry["key"], is_secret=entry["is_secret"],
            # .get() with a default: snapshots taken before layout metadata
            # existed won't have these keys — restoring one just resets
            # display metadata to defaults, never fails.
            order=entry.get("order", 0), group_name=entry.get("group_name", ""),
            leading_comment=entry.get("leading_comment", ""),
        )
        if entry["is_secret"]:
            var.encrypted_value = bytes.fromhex(entry["encrypted_value"]) if entry["encrypted_value"] else None
        else:
            var.value = entry["value"] or ""
        var.save()

    _bump_revision_and_write(environment, user)
    audit(user=user, action=AuditLog.Action.RESTORE, target=str(revision_number),
          project=environment.project, environment=environment)
    return environment


def reveal_variable(*, environment: Environment, user, key: str) -> str:
    try:
        var = Variable.objects.get(environment=environment, key=key)
    except Variable.DoesNotExist:
        raise NotFound(f"variable not found: {key}")
    if not var.is_secret:
        return var.value
    value = decrypt_value(var.encrypted_value)
    audit(user=user, action=AuditLog.Action.REVEAL, target=key,
          project=environment.project, environment=environment)
    return value


@transaction.atomic
def set_lock(*, environment_id, locked: bool, actor_label: str) -> Environment:
    environment = Environment.objects.select_for_update().get(pk=environment_id)
    environment.locked_for_deploy = locked
    environment.save(update_fields=["locked_for_deploy"])
    audit(user=None, action=AuditLog.Action.LOCK if locked else AuditLog.Action.UNLOCK,
          target=actor_label, project=environment.project, environment=environment)
    return environment
