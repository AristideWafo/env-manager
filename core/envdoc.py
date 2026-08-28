"""
Structured .env document model: parse a real .env file into an editable tree
(groups, variables, comments, blank lines, raw/unknown lines) that preserves
order and formatting, and serialize it back.

This is deliberately separate from envfile.py's render_dotenv/parse_dotenv,
which are the app's own canonical DB<->file format (always sorted, always
double-quoted — the source of truth for what the CI/CD pipeline reads). This
module is the *document* layer: it understands the real-world .env dialect
(comments, groups, unquoted/quoted values, blank lines) well enough to let a
human edit an existing file without losing its structure. It has no knowledge
of Variable/Environment/encryption — see DATA_MODEL.md before wiring it to
the DB in a follow-up change.

Design decisions (see PR description / conversation for the full rationale):
- Flat groups only, no nesting. A group runs from its header comment to the
  next group header or EOF.
- A "group header" comment is `# <run of >=3 identical punctuation><title>
  <run of >=3 identical punctuation>` with a non-empty title. Anything else
  starting with `#` is a plain Comment, never assumed to be a group.
- Comments are sibling nodes, not fields attached to a Variable/Group. This
  keeps the parser dumb (no attachment heuristics) and makes "move a
  comment" a real, independent operation.
- `#` starts a comment only as the first non-whitespace character of a line
  — no inline comments. This makes `FOO=#value` and `FOO="value # x"`
  unambiguous instead of guessing based on quoting.
- Every node caches its exact original source line in `.raw`. Serializing an
  untouched node re-emits `.raw` verbatim (byte-for-byte round trip). Any
  edit operation clears `.raw` to None, which forces that one line to be
  regenerated from its parsed fields on the next serialize() — untouched
  lines elsewhere in the file are never touched.
- Unquoted values are never trimmed/altered on parse or on unmodified
  re-serialize — only an explicit edit changes a value.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

__all__ = [
    "Blank",
    "Raw",
    "Comment",
    "Variable",
    "Group",
    "Document",
    "ParseIssue",
    "parse",
    "serialize",
    "validate",
]

# --- id -----------------------------------------------------------------

def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# --- node types -----------------------------------------------------------

@dataclass
class Blank:
    id: str = field(default_factory=_new_id)


@dataclass
class Raw:
    """A line the parser could not interpret as comment/blank/variable.
    Never dropped — preserved verbatim so no information is lost (per the
    'never silently ignore a line' rule)."""

    text: str
    id: str = field(default_factory=_new_id)


@dataclass
class Comment:
    text: str  # content after '#' and one optional leading space
    raw: str | None = None  # exact original line; None once edited
    id: str = field(default_factory=_new_id)

    @staticmethod
    def new(text: str) -> "Comment":
        return Comment(text=text, raw=None)


@dataclass
class Variable:
    key: str
    value: str = ""
    is_export: bool = False
    quote: str | None = None  # None (unquoted), '"', or "'" — preferred style
    raw: str | None = None  # exact original line; None once edited
    id: str = field(default_factory=_new_id)

    def set_value(self, value: str, quote: str | None = "keep") -> None:
        """quote='keep' (default) preserves current quote preference;
        pass None/'"'/"'" to change it. Always clears the raw cache."""
        self.value = value
        if quote != "keep":
            self.quote = quote
        self.raw = None

    def rename(self, key: str) -> None:
        self.key = key
        self.raw = None


@dataclass
class Group:
    name: str
    flank_char: str = "-"
    flank_len: int = 3
    raw: str | None = None  # exact original header line; None once edited
    children: list = field(default_factory=list)  # Comment|Variable|Blank|Raw
    id: str = field(default_factory=_new_id)

    def variables(self):
        return [c for c in self.children if isinstance(c, Variable)]

    def rename(self, name: str) -> None:
        self.name = name
        self.raw = None


@dataclass
class Document:
    children: list = field(default_factory=list)  # Group|Comment|Variable|Blank|Raw

    # --- lookup helpers ---------------------------------------------------

    def all_variables(self):
        """Yields (container, index, Variable) for every variable, group or
        top-level, in document order."""
        for i, node in enumerate(self.children):
            if isinstance(node, Variable):
                yield self, i, node
            elif isinstance(node, Group):
                for j, gc in enumerate(node.children):
                    if isinstance(gc, Variable):
                        yield node, j, gc

    def find_variable(self, key: str) -> Variable | None:
        for _, _, var in self.all_variables():
            if var.key == key:
                return var
        return None

    def find_group(self, name: str) -> Group | None:
        for node in self.children:
            if isinstance(node, Group) and node.name == name:
                return node
        return None

    # --- variable operations ----------------------------------------------

    def create_variable(self, key: str, value: str = "", *, group: str | None = None,
                         is_export: bool = False, quote: str | None = None) -> Variable:
        if self.find_variable(key) is not None:
            raise ValueError(f"variable already exists: {key}")
        var = Variable(key=key, value=value, is_export=is_export, quote=quote, raw=None)
        container = self.find_group(group) if group else self
        if group and container is None:
            raise ValueError(f"group not found: {group}")
        container.children.append(var)
        return var

    def delete_variable(self, key: str) -> None:
        for node in [self, *[c for c in self.children if isinstance(c, Group)]]:
            container = node
            for i, c in enumerate(container.children):
                if isinstance(c, Variable) and c.key == key:
                    del container.children[i]
                    return
        raise ValueError(f"variable not found: {key}")

    def move_variable(self, key: str, *, group: str | None, index: int | None = None) -> None:
        """Move a variable to `group` (None = top level), at `index` within
        the destination's children (default: append at end)."""
        var = self.find_variable(key)
        if var is None:
            raise ValueError(f"variable not found: {key}")
        self.delete_variable(key)
        dest = self.find_group(group) if group else self
        if group and dest is None:
            raise ValueError(f"group not found: {group}")
        if index is None:
            dest.children.append(var)
        else:
            dest.children.insert(index, var)

    # --- group operations ---------------------------------------------------

    def create_group(self, name: str, *, index: int | None = None) -> Group:
        if self.find_group(name) is not None:
            raise ValueError(f"group already exists: {name}")
        grp = Group(name=name, raw=None)
        if index is None:
            self.children.append(grp)
        else:
            self.children.insert(index, grp)
        return grp

    def rename_group(self, old_name: str, new_name: str) -> None:
        grp = self.find_group(old_name)
        if grp is None:
            raise ValueError(f"group not found: {old_name}")
        if new_name != old_name and self.find_group(new_name) is not None:
            raise ValueError(f"group already exists: {new_name}")
        grp.rename(new_name)

    def delete_group(self, name: str, *, keep_children: bool = True) -> None:
        """Deletes the group header. By default its children (variables,
        comments, ...) are hoisted to top level in place, never silently
        discarded; pass keep_children=False to drop them too."""
        for i, node in enumerate(self.children):
            if isinstance(node, Group) and node.name == name:
                del self.children[i]
                if keep_children and node.children:
                    self.children[i:i] = node.children
                return
        raise ValueError(f"group not found: {name}")

    def move_group(self, name: str, *, index: int) -> None:
        grp = self.find_group(name)
        if grp is None:
            raise ValueError(f"group not found: {name}")
        self.children.remove(grp)
        self.children.insert(index, grp)

    # --- comment operations -------------------------------------------------

    def add_comment(self, text: str, *, group: str | None = None, index: int | None = None) -> Comment:
        comment = Comment.new(text)
        container = self.find_group(group) if group else self
        if group and container is None:
            raise ValueError(f"group not found: {group}")
        if index is None:
            container.children.append(comment)
        else:
            container.children.insert(index, comment)
        return comment

    def _find_comment(self, comment_id: str):
        for node in [self, *[c for c in self.children if isinstance(c, Group)]]:
            for i, c in enumerate(node.children):
                if isinstance(c, Comment) and c.id == comment_id:
                    return node, i, c
        return None

    def update_comment(self, comment_id: str, text: str) -> None:
        found = self._find_comment(comment_id)
        if found is None:
            raise ValueError(f"comment not found: {comment_id}")
        _, _, comment = found
        comment.text = text
        comment.raw = None

    def delete_comment(self, comment_id: str) -> None:
        found = self._find_comment(comment_id)
        if found is None:
            raise ValueError(f"comment not found: {comment_id}")
        container, i, _ = found
        del container.children[i]

    def move_comment(self, comment_id: str, *, group: str | None, index: int | None = None) -> None:
        found = self._find_comment(comment_id)
        if found is None:
            raise ValueError(f"comment not found: {comment_id}")
        container, i, comment = found
        del container.children[i]
        dest = self.find_group(group) if group else self
        if group and dest is None:
            raise ValueError(f"group not found: {group}")
        if index is None:
            dest.children.append(comment)
        else:
            dest.children.insert(index, comment)


# --- parsing ----------------------------------------------------------------

_GROUP_RE = re.compile(r"^#\s*([=\-]{3,})\s+(.+?)\s+([=\-]{3,})\s*$")
_VAR_RE = re.compile(r"^(export\s+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*=(.*)$")


def _decode_value(raw_value: str) -> tuple[str, str | None]:
    """Returns (decoded_value, quote). No trimming for unquoted values —
    whatever's between '=' and end of line is kept exactly."""
    if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] == '"':
        inner = raw_value[1:-1]
        return _unescape_double(inner), '"'
    if len(raw_value) >= 2 and raw_value[0] == raw_value[-1] == "'":
        return raw_value[1:-1], "'"
    return raw_value, None


def _unescape_double(value: str) -> str:
    out = []
    i = 0
    while i < len(value):
        c = value[i]
        if c == "\\" and i + 1 < len(value) and value[i + 1] in ('\\', '"', "n"):
            nxt = value[i + 1]
            out.append({"\\": "\\", '"': '"', "n": "\n"}[nxt])
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _escape_double(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def encode_value(value: str, quote: str | None) -> str:
    """Inverse of _decode_value, used to (re)render an edited variable."""
    if quote == '"':
        return f'"{_escape_double(value)}"'
    if quote == "'":
        if "'" in value:
            return f'"{_escape_double(value)}"'  # auto-upgrade, can't escape in '...'
        return f"'{value}'"
    # unquoted: auto-upgrade if the bare value contains whitespace (leading,
    # trailing, internal, or a newline) — otherwise leave it bare. A leading
    # '#' is NOT unsafe here: this dialect only treats '#' as a comment when
    # it's the first character of the whole line, never after '=' (see
    # module docstring), so `FOO=#value` round-trips fine unquoted.
    if value != "" and any(c.isspace() for c in value):
        return f'"{_escape_double(value)}"'
    return value


def parse(source: str) -> Document:
    doc = Document()
    current_group: Group | None = None

    def append(node) -> None:
        (current_group.children if current_group is not None else doc.children).append(node)

    for line in source.splitlines():
        stripped = line.strip()

        if stripped == "":
            append(Blank())
            continue

        if stripped.startswith("#"):
            m = _GROUP_RE.match(stripped)
            if m and m.group(2):
                flank_char = m.group(1)[0]
                current_group = Group(
                    name=m.group(2), flank_char=flank_char, flank_len=len(m.group(1)), raw=line,
                )
                doc.children.append(current_group)
                continue
            text = stripped[1:]
            if text.startswith(" "):
                text = text[1:]
            append(Comment(text=text, raw=line))
            continue

        m = _VAR_RE.match(line)
        if m:
            is_export, key, raw_value = m.groups()
            value, quote = _decode_value(raw_value)
            append(Variable(key=key, value=value, is_export=bool(is_export), quote=quote, raw=line))
            continue

        append(Raw(text=line))

    return doc


# --- serialization ------------------------------------------------------------

def _render_comment(c: Comment) -> str:
    if c.raw is not None:
        return c.raw
    return f"# {c.text}" if c.text else "#"


def _render_variable(v: Variable) -> str:
    if v.raw is not None:
        return v.raw
    prefix = "export " if v.is_export else ""
    return f"{prefix}{v.key}={encode_value(v.value, v.quote)}"


def _render_group_header(g: Group) -> str:
    if g.raw is not None:
        return g.raw
    flank = g.flank_char * g.flank_len
    return f"# {flank} {g.name} {flank}"


def _render_node(node) -> str:
    if isinstance(node, Blank):
        return ""
    if isinstance(node, Raw):
        return node.text
    if isinstance(node, Comment):
        return _render_comment(node)
    if isinstance(node, Variable):
        return _render_variable(node)
    raise TypeError(f"not a line-level node: {node!r}")


def serialize(doc: Document) -> str:
    lines = []
    for node in doc.children:
        if isinstance(node, Group):
            lines.append(_render_group_header(node))
            for child in node.children:
                lines.append(_render_node(child))
        else:
            lines.append(_render_node(node))
    return "\n".join(lines) + ("\n" if lines else "")


# --- validation -----------------------------------------------------------

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class ParseIssue:
    severity: str  # "error" | "warning"
    code: str
    message: str
    node_id: str | None = None


def validate(doc: Document) -> list[ParseIssue]:
    issues: list[ParseIssue] = []
    seen_keys: dict[str, int] = {}
    seen_groups: dict[str, int] = {}

    for node in doc.children:
        if isinstance(node, Group):
            seen_groups[node.name] = seen_groups.get(node.name, 0) + 1
            if not node.children:
                issues.append(ParseIssue("warning", "empty_group", f"group {node.name!r} has no content", node.id))
            for child in node.children:
                if isinstance(child, Variable):
                    seen_keys[child.key] = seen_keys.get(child.key, 0) + 1
                    if not _KEY_RE.match(child.key):
                        issues.append(ParseIssue("error", "invalid_key", f"invalid variable key: {child.key!r}", child.id))
        elif isinstance(node, Variable):
            seen_keys[node.key] = seen_keys.get(node.key, 0) + 1
            if not _KEY_RE.match(node.key):
                issues.append(ParseIssue("error", "invalid_key", f"invalid variable key: {node.key!r}", node.id))

    for key, count in seen_keys.items():
        if count > 1:
            issues.append(ParseIssue("error", "duplicate_key", f"duplicate variable key: {key!r} ({count} occurrences)"))
    for name, count in seen_groups.items():
        if count > 1:
            issues.append(ParseIssue("warning", "duplicate_group", f"duplicate group name: {name!r} ({count} occurrences)"))

    return issues
