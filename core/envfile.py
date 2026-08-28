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
    """
    lines = []
    for var in variables:
        key = var["key"]
        value = var["value"] or ""
        # Minimal, predictable .env quoting: wrap in double quotes and escape
        # backslash/quote/newline so the CI/CD .env parser gets a single line.
        escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        lines.append(f'{key}="{escaped}"')
    return "\n".join(lines) + ("\n" if lines else "")


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
    path = resolve_environment_path(environment)
    content = render_dotenv(decrypted_variables)
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
    """Parse the KEY="value" format render_dotenv writes back into
    [{"key": ..., "value": ...}, ...]. Lines that don't match are skipped
    (e.g. a pre-existing file hand-edited outside the app)."""
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
