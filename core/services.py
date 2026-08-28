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
            "group_flank_char": var.group_flank_char,
            "group_flank_len": var.group_flank_len,
        })
    return snap


def _decrypted_variables_for_file(environment: Environment) -> list[dict]:
    """In display order (Variable.order), with group/comment/header-style —
    see envfile.render_document, which builds the file's group/comment
    structure from exactly these fields."""
    out = []
    for var in environment.variables.all().order_by("order"):
        value = decrypt_value(var.encrypted_value) if var.is_secret else var.value
        out.append({
            "key": var.key, "value": value, "group": var.group_name, "comment": var.leading_comment,
            "flank_char": var.group_flank_char, "flank_len": var.group_flank_len,
        })
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
def create_variable(*, environment_id, user, key, value, is_secret, group_name="", leading_comment="") -> Variable:
    """group_name/leading_comment are set (and, if a group is given,
    positioned contiguously with the rest of that group —
    _normalize_group_contiguity) BEFORE the file write below, so the write
    reflects the variable's final group/comment on the first try — setting
    them via a separate update_variable_layout() call afterward would write
    the file once ungrouped/uncommented, then never rewrite it to match."""
    environment = Environment.objects.select_for_update().get(pk=environment_id)
    if environment.locked_for_deploy:
        raise EnvironmentLocked()
    validate_key(key)
    if Variable.objects.filter(environment=environment, key=key).exists():
        raise ValidationError(f"variable already exists: {key}")
    var = Variable(
        environment=environment, key=key, is_secret=is_secret, order=_next_order(environment),
        group_name=group_name, leading_comment=leading_comment,
    )
    _set_value(var, value, is_secret)
    var.save()
    if group_name:
        _normalize_group_contiguity(environment)
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


def _group_blocks(environment) -> list[tuple[str | None, list[str]]]:
    """Partitions the environment's variables (in current `order`) into
    contiguous blocks: a run of variables sharing a non-empty group_name is
    one block — the group-contiguity invariant (see module notes above
    reorder_variables) guarantees this partition is unambiguous, i.e. the
    same group name never appears in two separate blocks. Each ungrouped
    variable is its own singleton block (group=None): ungrouped variables
    never need to stay together."""
    blocks: list[tuple[str | None, list[str]]] = []
    for var in environment.variables.order_by("order"):
        g = var.group_name or None
        if g is not None and blocks and blocks[-1][0] == g:
            blocks[-1][1].append(var.key)
        else:
            blocks.append((g, [var.key]))
    return blocks


def _validate_block_contiguity(ordered_keys: list[str], existing: dict) -> None:
    """Raises ValidationError if ordered_keys would split a group: the same
    non-empty group_name closing and later reopening. `existing` maps
    key -> Variable (for its current group_name)."""
    closed = set()
    current = None
    for key in ordered_keys:
        g = existing[key].group_name or None
        if g != current:
            if current is not None:
                closed.add(current)
            if g is not None and g in closed:
                raise ValidationError(
                    f"reorder would split group {g!r}: its members must stay contiguous"
                )
            current = g


def _normalize_group_contiguity(environment) -> None:
    """Repairs the invariant after a raw group_name write (update_variable_
    layout, import): if the same group name now appears in more than one
    block — e.g. a variable was just reassigned into a group that already
    has members elsewhere, or import appended new members of an
    already-present group at the end — merges those blocks into one,
    keeping the first block's position and each block's internal order
    (so newly added/moved members land at the end of the group). Rewrites
    `order` directly; no audit entry (this is bookkeeping, not a
    user-visible reorder — the caller's own audit entry covers the action
    that necessitated it)."""
    blocks = _group_blocks(environment)
    seen_at: dict[str, int] = {}
    merged: list[tuple[str | None, list[str]]] = []
    for group, keys in blocks:
        if group is not None and group in seen_at:
            merged[seen_at[group]][1].extend(keys)
        else:
            if group is not None:
                seen_at[group] = len(merged)
            merged.append((group, list(keys)))
    ordered_keys = [k for _, keys in merged for k in keys]
    existing = {v.key: v for v in environment.variables.all()}
    for i, key in enumerate(ordered_keys):
        var = existing[key]
        if var.order != i:
            var.order = i
            var.save(update_fields=["order"])


@transaction.atomic
def update_variable_layout(*, environment_id, user, key, group_name=None, leading_comment=None) -> Variable:
    """Structured-editor metadata only (core/envdoc.py concepts: which group a
    variable displays under, its leading comment). Never touches
    value/encrypted_value and never bumps the revision or writes the file
    itself — but the next value-triggered write (_bump_revision_and_write)
    renders using whatever group_name/leading_comment/order currently hold
    (envfile.render_document), so this IS what puts a group/comment into the
    file, just not synchronously. Allowed even when the environment is
    locked_for_deploy, since it can't change what's currently deployed.
    Pass None (the default) to leave a field unchanged.

    Changing group_name repositions the variable to stay contiguous with
    its new group (see _normalize_group_contiguity) — the group-contiguity
    invariant must never be left broken by this call."""
    environment = Environment.objects.select_for_update().get(pk=environment_id)
    try:
        var = Variable.objects.get(environment=environment, key=key)
    except Variable.DoesNotExist:
        raise NotFound(f"variable not found: {key}")
    update_fields = []
    group_changed = group_name is not None and group_name != var.group_name
    if group_name is not None:
        var.group_name = group_name
        update_fields.append("group_name")
    if leading_comment is not None:
        var.leading_comment = leading_comment
        update_fields.append("leading_comment")
    if update_fields:
        var.save(update_fields=update_fields)
    if group_changed:
        _normalize_group_contiguity(environment)
    audit(user=user, action=AuditLog.Action.UPDATE, target=f"layout:{key}",
          project=environment.project, environment=environment)
    return var


@transaction.atomic
def reorder_variables(*, environment_id, user, ordered_keys: list[str]) -> None:
    """Reassigns display order (0..N-1) to match ordered_keys exactly.
    Metadata-only — see update_variable_layout. ordered_keys must be exactly
    the environment's current variable keys, each once; a partial or stale
    list is rejected rather than silently reordering a subset. Also rejects
    an ordered_keys that would split a group (group-contiguity invariant —
    see _group_blocks) — an ungrouped variable, or a member of a different
    group, may never sit between two members of the same group."""
    environment = Environment.objects.select_for_update().get(pk=environment_id)
    existing = {v.key: v for v in environment.variables.all()}
    if sorted(ordered_keys) != sorted(existing.keys()) or len(ordered_keys) != len(set(ordered_keys)):
        raise ValidationError(
            "ordered_keys must contain exactly the environment's current variable keys, each once"
        )
    _validate_block_contiguity(ordered_keys, existing)
    for i, key in enumerate(ordered_keys):
        var = existing[key]
        if var.order != i:
            var.order = i
            var.save(update_fields=["order"])
    audit(user=user, action=AuditLog.Action.UPDATE, target="reorder",
          project=environment.project, environment=environment)


def swap_variable_order(*, environment_id, user, key, direction: str) -> None:
    """Moves a variable one step up/down in display order — group-aware:
    if key sits inside a multi-member group and isn't at that group's edge,
    swaps it with its immediate neighbor *inside the group* (safe, doesn't
    touch contiguity). If key is at its own block's edge (an ungrouped
    variable, or a grouped variable that can't move further within its
    group without leaving it), swaps its whole block with the adjacent
    block instead — so a group always moves as one unit relative to
    whatever's next to it, and the group-contiguity invariant can never be
    broken by this operation. Use update_variable_layout to actually move a
    variable into/out of a group."""
    if direction not in ("up", "down"):
        raise ValidationError(f"invalid direction: {direction!r} (must be 'up' or 'down')")
    environment = Environment.objects.select_for_update().get(pk=environment_id)
    blocks = [(g, list(keys)) for g, keys in _group_blocks(environment)]
    block_index = next((i for i, (_, keys) in enumerate(blocks) if key in keys), None)
    if block_index is None:
        raise NotFound(f"variable not found: {key}")
    step = -1 if direction == "up" else 1
    _, block_keys = blocks[block_index]
    pos = block_keys.index(key)
    new_pos = pos + step
    if 0 <= new_pos < len(block_keys):
        block_keys[pos], block_keys[new_pos] = block_keys[new_pos], block_keys[pos]
    else:
        neighbor_index = block_index + step
        if 0 <= neighbor_index < len(blocks):
            blocks[block_index], blocks[neighbor_index] = blocks[neighbor_index], blocks[block_index]
    ordered_keys = [k for _, keys in blocks for k in keys]
    reorder_variables(environment_id=environment_id, user=user, ordered_keys=ordered_keys)


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
    """Full sync from what's already on disk for this environment's .env
    file — either the first-visit auto-import of a file that predates this
    environment being declared in the app, or a manual "Refresh from file"
    (see views.environment_refresh_view). The file is the source of truth:
    a key already tracked in the DB gets its value AND its layout (group,
    leading comment, header flank style, position) overwritten to match
    what's on disk, not just filled in when missing. A key present in the
    DB but no longer in the file is left alone (untracked-from-file, not
    deleted) and pushed after the file's keys, in its previous relative
    order, so it survives the next write instead of vanishing.

    Uses core/envdoc.py to understand the real .env dialect (comments,
    groups, unquoted values). The parsed group/leading-comment/order are
    stored on Variable and feed back into the next write
    (envfile.render_document) — that's the point: re-running this against a
    hand-edited file picks up its structure. Order is assigned straight
    from document position, so group-contiguity falls out for free (no
    separate _normalize_group_contiguity pass needed).

    A changed variable's is_secret flag is left as-is — the file only ever
    holds plaintext, so there's no signal in it to flip that flag either
    way — and the file gets rewritten unconditionally on every change,
    guaranteeing the sync bumps the revision (so history/optimistic
    concurrency see it) even though the write is a no-op for the on-disk
    bytes themselves.

    Returns the number of variables created or updated."""
    environment = Environment.objects.select_for_update().get(pk=environment_id)
    if environment.locked_for_deploy:
        raise EnvironmentLocked()
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

    existing = {v.key: v for v in environment.variables.all()}
    document = envdoc.parse(content)
    created = updated = 0
    seen_keys = set()
    order = 1
    for container, index, entry in document.all_variables():
        seen_keys.add(entry.key)
        is_grouped = isinstance(container, envdoc.Group)
        group_name = container.name if is_grouped else ""
        leading_comment = _leading_comment_for(container, index)
        flank_char = container.flank_char if is_grouped else "-"
        flank_len = container.flank_len if is_grouped else 3

        var = existing.get(entry.key)
        if var is None:
            var = Variable(environment=environment, key=entry.key, is_secret=False)
            _set_value(var, entry.value, False)
            var.group_name, var.leading_comment = group_name, leading_comment
            var.group_flank_char, var.group_flank_len = flank_char, flank_len
            var.order = order
            var.save()
            created += 1
        else:
            current_value = decrypt_value(var.encrypted_value) if var.is_secret else var.value
            changed = (
                current_value != entry.value or var.group_name != group_name
                or var.leading_comment != leading_comment or var.group_flank_char != flank_char
                or var.group_flank_len != flank_len or var.order != order
            )
            if changed:
                if current_value != entry.value:
                    _set_value(var, entry.value, var.is_secret)
                var.group_name, var.leading_comment = group_name, leading_comment
                var.group_flank_char, var.group_flank_len = flank_char, flank_len
                var.order = order
                var.save()
                updated += 1
        order += 1

    # Keys tracked in the DB but no longer in the file: keep them, appended
    # after the file's keys in their previous relative order, rather than
    # deleting or leaving their order values colliding with the ones just
    # assigned above.
    for var in sorted((v for k, v in existing.items() if k not in seen_keys), key=lambda v: v.order):
        if var.order != order:
            var.order = order
            var.save(update_fields=["order"])
        order += 1

    if created or updated:
        audit(user=user, action=AuditLog.Action.UPDATE, target=f"refresh:{created} new, {updated} updated",
              project=environment.project, environment=environment)
        logger.info("refresh from file for environment %s: %d created, %d updated",
                    environment.id, created, updated)
        _bump_revision_and_write(environment, user)
    else:
        logger.info("refresh from file for environment %s: no changes (%d key(s) in sync)",
                    environment.id, len(existing))
    return created + updated


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
            group_flank_char=entry.get("group_flank_char", "-"),
            group_flank_len=entry.get("group_flank_len", 3),
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
