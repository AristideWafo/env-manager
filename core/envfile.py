"""
Filesystem safety layer: canonical path resolution against AllowedRoot, and
atomic .env writes (tmp file -> fsync -> rename).

AGENT_CONTEXT.md rule #1/#2: every filesystem write goes through here, and
every path is validated against allowed_roots before any I/O happens.
"""

import logging
import os
import re
from pathlib import Path

from django.conf import settings

from . import envdoc
from .models import AllowedRoot

logger = logging.getLogger(__name__)


class PathNotAllowed(Exception):
    """Raised when a resolved path escapes every declared AllowedRoot."""


def resolve_environment_path(environment) -> Path:
    """
    Resolve `<allowed_root.path>/<relative_path>` to a canonical absolute path
    and verify it is still a descendant of that root (blocks `..` traversal
    and symlink escape). Raises PathNotAllowed otherwise.
    """
    root = environment.project.allowed_root
    root_path = Path(root.path).resolve(strict=False)
    candidate = (root_path / environment.relative_path).resolve(strict=False)

    try:
        candidate.relative_to(root_path)
    except ValueError:
        raise PathNotAllowed(
            f"{candidate} is not a descendant of allowed root {root_path}"
        )

    # Re-check the root itself is still declared (not deleted/mutated since).
    if not AllowedRoot.objects.filter(path=str(root.path)).exists():
        raise PathNotAllowed(f"allowed root {root_path} is no longer declared")

    return candidate


def render_dotenv(variables: list[dict]) -> str:
    """
    variables: list of {"key": str, "value": str}. Secrets are passed already
    decrypted by the caller — this function has no knowledge of is_secret.

    Flat always-quoted format. No longer used by write_environment_file (see
    render_document below) — kept as a minimal, still-tested primitive; a
    correct dotenv renderer for callers that want the older, structure-free
    guarantee. Not reachable from any production write path as of the
    structured-editor work (core/envdoc.py).
    """
    lines = []
    for var in variables:
        key = var["key"]
        value = var["value"] or ""
        # Minimal, predictable .env quoting: wrap in double quotes and escape
        # backslash/quote/newline so a downstream .env parser gets a single line.
        escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        lines.append(f'{key}="{escaped}"')
    return "\n".join(lines) + ("\n" if lines else "")


def render_document(variables: list[dict]) -> str:
    """
    variables: list of {"key", "value", "group", "comment", "flank_char",
    "flank_len"}, IN DISPLAY ORDER (Variable.order — see models.py). Builds
    a core/envdoc.py Document — grouping contiguous same-group entries into
    a Group node (header style taken from the first member's flank_char/
    flank_len, e.g. "====" vs "---" — see models.Variable.group_flank_char),
    rendering each variable's leading_comment as Comment nodes right above
    it — and serializes it. Unlike render_dotenv, values are quoted only
    when unsafe unquoted (see envdoc.encode_value), and groups/comments/
    order actually reach the file.

    Relies on the group-contiguity invariant enforced in services.py
    (variables sharing a group_name are always contiguous in `order` —
    reorder_variables/swap_variable_order/update_variable_layout all
    maintain it) — this function does not itself detect or reject a split
    group, it just renders whatever order it's given.
    """
    doc = envdoc.Document()
    current_group_name = None
    current_container = doc
    started = False
    for var in variables:
        group = var.get("group") or None
        if not started or group != current_group_name:
            if started:
                doc.children.append(envdoc.Blank())
            if group:
                current_container = envdoc.Group(
                    name=group, raw=None,
                    flank_char=var.get("flank_char") or "-",
                    flank_len=var.get("flank_len") or 3,
                )
                doc.children.append(current_container)
            else:
                current_container = doc
            current_group_name = group
            started = True
        comment = var.get("comment") or ""
        for line in comment.splitlines():
            current_container.children.append(envdoc.Comment.new(line))
        current_container.children.append(
            envdoc.Variable(key=var["key"], value=var["value"] or "", quote=None, raw=None)
        )
    return envdoc.serialize(doc)


def atomic_write(path: Path, content: str) -> None:
    """tmp file in the same directory -> fsync -> os.replace (atomic rename)."""
    if not settings.ENV_MANAGER_FS_ENABLED:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)  # atomic on POSIX
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)  # persist the rename itself
        finally:
            os.close(dir_fd)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def write_environment_file(environment, decrypted_variables: list[dict]) -> None:
    """decrypted_variables: list of {"key", "value", "group", "comment"} in
    display order (see services._decrypted_variables_for_file)."""
    path = resolve_environment_path(environment)
    content = render_document(decrypted_variables)
    atomic_write(path, content)
    logger.info("wrote .env file for environment %s (%d variables)", environment.id, len(decrypted_variables))


_LINE_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)="((?:[^"\\]|\\.)*)"$')


def _unescape(value: str) -> str:
    """Reverse of render_dotenv's escaping, scanned left-to-right so the three
    escape sequences it introduces (\\\\, \\", \\n) can never be ambiguous."""
    out = []
    i = 0
    while i < len(value):
        c = value[i]
        if c == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            if nxt == "\\":
                out.append("\\")
                i += 2
                continue
            if nxt == '"':
                out.append('"')
                i += 2
                continue
            if nxt == "n":
                out.append("\n")
                i += 2
                continue
        out.append(c)
        i += 1
    return "".join(out)


def parse_dotenv(content: str) -> list[dict]:
    """Parse the KEY="value" format render_dotenv writes (no longer the
    production write format — see render_document) back into
    [{"key": ..., "value": ...}, ...]. Lines that don't match are skipped.
    Not used by import_variables_from_file, which uses core/envdoc.py's
    real-dialect parser instead; kept as a tested primitive."""
    variables = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _LINE_RE.match(line)
        if not m:
            # Never log the raw line: an unparseable line is very likely
            # `KEY=plaintext-secret` from a hand-edited legacy file, and this
            # path runs on import (AGENT_CONTEXT.md rule #3 — no secret
            # values in logs). Log only what's safe to identify the line by.
            key_guess = line.split("=", 1)[0].strip() if "=" in line else None
            logger.warning(
                "skipping unparseable .env line while importing (key=%s, length=%d)",
                key_guess or "<none>", len(line),
            )
            continue
        key, raw_value = m.groups()
        variables.append({"key": key, "value": _unescape(raw_value)})
    return variables


def read_environment_file(environment) -> str | None:
    """Read the current on-disk content for this environment's .env file, or
    None if it doesn't exist yet."""
    path = resolve_environment_path(environment)
    if not path.exists():
        return None
    return path.read_text()
