from pathlib import Path

import pytest

from core.envdoc import (
    Blank,
    Comment,
    Group,
    Raw,
    Variable,
    encode_value,
    parse,
    serialize,
    validate,
)

FIXTURE = Path(__file__).resolve().parent.parent.parent / ".env.example"


# --- round-trip on the real fixture -----------------------------------------

def test_roundtrip_on_real_fixture_is_byte_identical():
    original = FIXTURE.read_text()
    doc = parse(original)
    assert serialize(doc) == original


def test_fixture_groups_detected_in_order():
    doc = parse(FIXTURE.read_text())
    names = [n.name for n in doc.children if isinstance(n, Group)]
    assert names == [
        "Django",
        "Secrets encryption",
        "WebAuthn (passkeys)",
        "CI/CD integration (optional)",
        "Docker Compose only",
    ]


def test_fixture_top_level_preamble_comment_and_blank_before_first_group():
    doc = parse(FIXTURE.read_text())
    assert isinstance(doc.children[0], Comment)
    assert "Copy to .env" in doc.children[0].text
    assert isinstance(doc.children[1], Blank)
    assert isinstance(doc.children[2], Group)


def test_fixture_variable_inside_group_with_leading_comment():
    doc = parse(FIXTURE.read_text())
    django_group = doc.find_group("Django")
    keys_and_types = [(type(c).__name__, getattr(c, "key", None)) for c in django_group.children]
    assert ("Variable", "DJANGO_SECRET_KEY") in keys_and_types
    var = doc.find_variable("DJANGO_ALLOWED_HOSTS")
    assert var.value == "localhost,127.0.0.1"
    idx = django_group.children.index(var)
    assert isinstance(django_group.children[idx - 1], Comment)


def test_fixture_empty_values_preserved():
    doc = parse(FIXTURE.read_text())
    assert doc.find_variable("DJANGO_FORCE_SCRIPT_NAME").value == ""
    assert doc.find_variable("CI_API_TOKENS").value == ""


def test_fixture_reparsed_document_is_equal_after_roundtrip():
    original = FIXTURE.read_text()
    doc1 = parse(original)
    doc2 = parse(serialize(doc1))
    assert [v.key for _, _, v in doc1.all_variables()] == [v.key for _, _, v in doc2.all_variables()]
    assert [v.value for _, _, v in doc1.all_variables()] == [v.value for _, _, v in doc2.all_variables()]


# --- group header detection --------------------------------------------------

def test_dash_header_detected_as_group():
    doc = parse("# --- Database ------------------------------------------------\nDB_HOST=x\n")
    assert isinstance(doc.children[0], Group)
    assert doc.children[0].name == "Database"


def test_equals_header_detected_as_group():
    doc = parse("# ==================== Database ====================\nDB_HOST=x\n")
    assert isinstance(doc.children[0], Group)
    assert doc.children[0].name == "Database"


def test_empty_title_header_is_plain_comment_not_group():
    doc = parse("# ====================\nDB_HOST=x\n")
    assert isinstance(doc.children[0], Comment)
    assert isinstance(doc.children[1], Variable)


def test_short_punctuation_run_is_plain_comment_not_group():
    doc = parse("# -- not a group --\nDB_HOST=x\n")
    assert isinstance(doc.children[0], Comment)


# --- comment association -----------------------------------------------------

def test_multiple_comments_before_variable_are_separate_sibling_nodes():
    src = "# URL used by Promtail.\n# This changes between dev and staging.\nLOKI_PUSH_URL=http://loki:3100/loki/api/v1/push\n"
    doc = parse(src)
    assert [type(c).__name__ for c in doc.children] == ["Comment", "Comment", "Variable"]


def test_orphan_comment_is_preserved_not_dropped():
    doc = parse("# TODO: configure production\n")
    assert len(doc.children) == 1
    assert isinstance(doc.children[0], Comment)
    assert doc.children[0].text == "TODO: configure production"


# --- value dialect ------------------------------------------------------------

@pytest.mark.parametrize(
    "line,expected_value,expected_quote",
    [
        ('FOO=bar', "bar", None),
        ('FOO=', "", None),
        ('FOO="bar"', "bar", '"'),
        ("FOO='bar'", "bar", "'"),
        ('FOO=hello world', "hello world", None),
        ('FOO=https://example.com?a=1&b=2', "https://example.com?a=1&b=2", None),
        ('FOO=a=b=c', "a=b=c", None),
        ('FOO=#value', "#value", None),
        ('FOO="value # with comment"', "value # with comment", '"'),
    ],
)
def test_value_dialect(line, expected_value, expected_quote):
    doc = parse(line + "\n")
    var = doc.children[0]
    assert isinstance(var, Variable)
    assert var.value == expected_value
    assert var.quote == expected_quote


def test_leading_hash_line_is_never_treated_as_inline_comment_start():
    # '#' only starts a comment as the first non-whitespace char of a LINE,
    # never inside a value — already covered by FOO=#value above, this
    # checks the reverse: a genuine comment line is never mistaken for a var.
    doc = parse("# FOO=bar\n")
    assert isinstance(doc.children[0], Comment)


def test_export_prefix_recognized_and_roundtrips():
    src = "export FOO=bar\n"
    doc = parse(src)
    var = doc.children[0]
    assert var.is_export is True
    assert var.key == "FOO"
    assert serialize(doc) == src


def test_double_quote_escapes():
    doc = parse('FOO="has \\"quote\\" and \\\\ and\\nnewline"\n')
    assert doc.children[0].value == 'has "quote" and \\ and\nnewline'


def test_unquoted_value_never_trimmed():
    doc = parse("FOO=  padded  \n")
    assert doc.children[0].value == "  padded  "


def test_unicode_value_preserved():
    src = "GREETING=héllo wörld 日本語\n"
    doc = parse(src)
    assert doc.children[0].value == "héllo wörld 日本語"
    assert serialize(doc) == src


def test_blank_lines_preserved_count_and_position():
    src = "A=1\n\n\nB=2\n"
    doc = parse(src)
    assert [type(n).__name__ for n in doc.children] == ["Variable", "Blank", "Blank", "Variable"]
    assert serialize(doc) == src


def test_raw_unknown_line_preserved_not_dropped():
    src = "not a valid line at all !!\nA=1\n"
    doc = parse(src)
    assert isinstance(doc.children[0], Raw)
    assert doc.children[0].text == "not a valid line at all !!"
    assert serialize(doc) == src


# --- edit operations ------------------------------------------------------

def test_update_value_only_changes_its_own_line():
    original = FIXTURE.read_text()
    doc = parse(original)
    doc.find_variable("DJANGO_DEBUG").set_value("1")
    output = serialize(doc)
    reparsed = parse(output)
    assert reparsed.find_variable("DJANGO_DEBUG").value == "1"
    # every other variable's value is untouched
    for _, _, var in parse(original).all_variables():
        if var.key != "DJANGO_DEBUG":
            assert reparsed.find_variable(var.key).value == var.value


def test_create_variable_in_group():
    doc = parse(FIXTURE.read_text())
    doc.create_variable("NEW_VAR", "hello", group="Django")
    var = doc.find_group("Django").variables()[-1]
    assert var.key == "NEW_VAR"
    reparsed = parse(serialize(doc))
    assert reparsed.find_variable("NEW_VAR").value == "hello"


def test_create_variable_duplicate_key_rejected():
    doc = parse(FIXTURE.read_text())
    with pytest.raises(ValueError):
        doc.create_variable("DJANGO_DEBUG", "1")


def test_delete_variable():
    doc = parse(FIXTURE.read_text())
    doc.delete_variable("DJANGO_DEBUG")
    assert doc.find_variable("DJANGO_DEBUG") is None
    reparsed = parse(serialize(doc))
    assert reparsed.find_variable("DJANGO_DEBUG") is None


def test_delete_variable_not_found_raises():
    doc = parse(FIXTURE.read_text())
    with pytest.raises(ValueError):
        doc.delete_variable("NOPE")


def test_move_variable_between_groups():
    doc = parse(FIXTURE.read_text())
    doc.move_variable("CI_API_TOKENS", group="Django")
    assert doc.find_variable("CI_API_TOKENS") in doc.find_group("Django").variables()
    assert doc.find_variable("CI_API_TOKENS") not in doc.find_group("CI/CD integration (optional)").variables()


def test_create_group_and_move_variable_into_it():
    doc = parse(FIXTURE.read_text())
    doc.create_group("Custom")
    doc.move_variable("PROJECTS_ROOT", group="Custom")
    assert doc.find_variable("PROJECTS_ROOT") in doc.find_group("Custom").variables()


def test_rename_group():
    doc = parse(FIXTURE.read_text())
    doc.rename_group("Django", "Django Core")
    assert doc.find_group("Django") is None
    assert doc.find_group("Django Core") is not None
    reparsed = parse(serialize(doc))
    assert reparsed.find_group("Django Core") is not None


def test_delete_group_hoists_children_by_default():
    doc = parse(FIXTURE.read_text())
    var_before = doc.find_variable("DJANGO_SECRET_KEY")
    doc.delete_group("Django", keep_children=True)
    assert doc.find_group("Django") is None
    assert doc.find_variable("DJANGO_SECRET_KEY") is var_before  # still present, hoisted


def test_delete_group_can_drop_children():
    doc = parse(FIXTURE.read_text())
    doc.delete_group("Django", keep_children=False)
    assert doc.find_variable("DJANGO_SECRET_KEY") is None


def test_add_update_delete_comment():
    doc = parse(FIXTURE.read_text())
    c = doc.add_comment("a new note", group="Django")
    doc.update_comment(c.id, "an updated note")
    assert c.text == "an updated note"
    doc.delete_comment(c.id)
    assert doc._find_comment(c.id) is None


def test_move_comment():
    doc = parse(FIXTURE.read_text())
    c = doc.add_comment("movable note")
    doc.move_comment(c.id, group="Django", index=0)
    assert c in doc.find_group("Django").children


# --- encode_value edge cases --------------------------------------------------

def test_encode_value_auto_quotes_unsafe_unquoted_values():
    assert encode_value("has space", None) == '"has space"'
    assert encode_value(" pad", None) == '" pad"'
    assert encode_value("", None) == ""
    assert encode_value("safe", None) == "safe"


def test_encode_value_single_quote_auto_upgrades_on_apostrophe():
    assert encode_value("it's here", "'") == '"it\'s here"'


# --- validation -----------------------------------------------------------

def test_validate_clean_fixture_has_no_errors():
    doc = parse(FIXTURE.read_text())
    issues = validate(doc)
    assert not any(i.severity == "error" for i in issues)


def test_validate_detects_duplicate_key():
    doc = parse("A=1\nA=2\n")
    issues = validate(doc)
    assert any(i.code == "duplicate_key" for i in issues)


def test_validate_detects_duplicate_group():
    doc = parse("# --- X ---\nA=1\n# --- X ---\nB=2\n")
    issues = validate(doc)
    assert any(i.code == "duplicate_group" for i in issues)


def test_validate_flags_empty_group_as_warning_not_error():
    doc = parse("# --- Empty ---\n")
    issues = validate(doc)
    assert any(i.code == "empty_group" and i.severity == "warning" for i in issues)


def test_validate_detects_invalid_key():
    doc = parse(FIXTURE.read_text())
    doc.children.append(Variable(key="1BAD", value="x"))
    issues = validate(doc)
    assert any(i.code == "invalid_key" for i in issues)
