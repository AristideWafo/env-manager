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

from .envfile import PathNotAllowed, parse_dotenv, read_environment_file, write_environment_file
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
    }


def _snapshot(environment: Environment) -> list[dict]:
    snap = []
    for var in environment.variables.all().order_by("key"):
        snap.append({
            "key": var.key,
            "value": var.value if not var.is_secret else None,
            "encrypted_value": var.encrypted_value.hex() if var.encrypted_value else None,
            "is_secret": var.is_secret,
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

    for op in operations:
        action, key = op["op"], op["key"]
        if action == "create":
            var = Variable(environment=environment, key=key, is_secret=bool(op.get("is_secret")))
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
    var = Variable(environment=environment, key=key, is_secret=is_secret)
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
def import_variables_from_file(*, environment_id, user) -> int:
    """Populate untracked Variable rows from what's already on disk for this
    environment's .env file (e.g. an existing file that predates this
    environment being declared in the app). Keys already tracked in the DB
    are left untouched — this only fills gaps, never overwrites. Does not
    bump the revision or rewrite the file, since its content already matches.
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
    imported = 0
    for entry in parse_dotenv(content):
        if entry["key"] in existing_keys:
            continue
        var = Variable(environment=environment, key=entry["key"], is_secret=False)
        _set_value(var, entry["value"], False)
        var.save()
        existing_keys.add(entry["key"])
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
        var = Variable(environment=environment, key=entry["key"], is_secret=entry["is_secret"])
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
