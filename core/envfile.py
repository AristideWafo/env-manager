"""
Filesystem safety layer: canonical path resolution against AllowedRoot, and
atomic .env writes (tmp file -> fsync -> rename).

AGENT_CONTEXT.md rule #1/#2: every filesystem write goes through here, and
every path is validated against allowed_roots before any I/O happens.
"""

import os
from pathlib import Path

from django.conf import settings

from .models import AllowedRoot


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
