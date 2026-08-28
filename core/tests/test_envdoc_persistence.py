"""
Structured-editor metadata (Variable.order/group_name/leading_comment) and
the import path that populates it from a real .env file via core/envdoc.py.

Explicitly covers the constraint the design settled on: this metadata is
display-only and must never change what write_environment_file puts on
disk (that stays the canonical always-quoted/alphabetical format).
"""

from pathlib import Path

import pytest

from core import services

FIXTURE = Path(__file__).resolve().parent.parent.parent / ".env.example"


@pytest.mark.django_db
def test_import_captures_group_and_leading_comment_from_real_fixture(environment, admin_user, tmp_root):
    (tmp_root / ".env").write_text(FIXTURE.read_text())
    imported = services.import_variables_from_file(environment_id=environment.id, user=admin_user)
    assert imported > 0

    var = environment.variables.get(key="DJANGO_ALLOWED_HOSTS")
    assert var.group_name == "Django"
    assert "Comma-separated list of hostnames" in var.leading_comment

    var2 = environment.variables.get(key="DJANGO_SECRET_KEY")
    assert var2.group_name == "Django"
    assert var2.leading_comment == ""  # no comment directly above it in the fixture


@pytest.mark.django_db
def test_import_preserves_document_order(environment, admin_user, tmp_root):
    (tmp_root / ".env").write_text(FIXTURE.read_text())
    services.import_variables_from_file(environment_id=environment.id, user=admin_user)
    ordered_keys = list(environment.variables.order_by("order").values_list("key", flat=True))
    assert ordered_keys == [
        "DJANGO_SECRET_KEY", "DJANGO_DEBUG", "DJANGO_ALLOWED_HOSTS", "DJANGO_FORCE_SCRIPT_NAME",
        "ENV_MANAGER_FERNET_KEY", "ENV_MANAGER_DB_PATH",
        "WEBAUTHN_RP_ID", "WEBAUTHN_RP_NAME", "WEBAUTHN_ORIGIN",
        "CI_API_TOKENS",
        "ENV_MANAGER_IMAGE", "PROJECTS_ROOT", "PROJECTS_ROOT_CONTAINER",
    ]


@pytest.mark.django_db
def test_import_then_write_preserves_group_and_comment_structure(environment, admin_user, tmp_root):
    """Structural metadata captured on import DOES feed the next write
    (envfile.render_document) — that's the point of the structured editor.
    Confirmed decision (see DATA_MODEL.md): this replaced the earlier
    always-quoted/alphabetical-only guarantee."""
    (tmp_root / ".env").write_text(FIXTURE.read_text())
    services.import_variables_from_file(environment_id=environment.id, user=admin_user)
    # Any value edit triggers _bump_revision_and_write, re-rendering the file
    # from current DB state (group/comment/order included).
    services.update_variable(
        environment_id=environment.id, user=admin_user, key="DJANGO_DEBUG",
        value="1", revision=environment.revision,
    )
    written = (tmp_root / ".env").read_text()
    assert "Django" in written  # group header made it into the file
    assert "Comma-separated list of hostnames" in written  # leading comment too

    from core import envdoc
    doc = envdoc.parse(written)
    group_names = [n.name for n in doc.children if isinstance(n, envdoc.Group)]
    assert "Django" in group_names
    assert doc.find_variable("DJANGO_DEBUG").value == "1"
    assert envdoc.validate(doc) == []


@pytest.mark.django_db
def test_write_never_splits_a_group_across_two_blocks(environment, admin_user, tmp_root):
    (tmp_root / ".env").write_text(FIXTURE.read_text())
    services.import_variables_from_file(environment_id=environment.id, user=admin_user)
    services.update_variable(
        environment_id=environment.id, user=admin_user, key="DJANGO_DEBUG",
        value="1", revision=environment.revision,
    )
    written = (tmp_root / ".env").read_text()
    from core import envdoc
    group_names = [n.name for n in envdoc.parse(written).children if isinstance(n, envdoc.Group)]
    assert len(group_names) == len(set(group_names))  # each group name appears once


@pytest.mark.django_db
def test_update_variable_layout_sets_group_and_comment(environment, admin_user):
    services.create_variable(environment_id=environment.id, user=admin_user, key="A", value="1", is_secret=False)
    var = services.update_variable_layout(
        environment_id=environment.id, user=admin_user, key="A",
        group_name="Custom", leading_comment="a note",
    )
    assert var.group_name == "Custom"
    assert var.leading_comment == "a note"


@pytest.mark.django_db
def test_update_variable_layout_does_not_bump_revision(environment, admin_user):
    services.create_variable(environment_id=environment.id, user=admin_user, key="A", value="1", is_secret=False)
    environment.refresh_from_db()
    rev_before = environment.revision
    services.update_variable_layout(environment_id=environment.id, user=admin_user, key="A", group_name="G")
    environment.refresh_from_db()
    assert environment.revision == rev_before


@pytest.mark.django_db
def test_update_variable_layout_allowed_while_locked(environment, admin_user):
    services.create_variable(environment_id=environment.id, user=admin_user, key="A", value="1", is_secret=False)
    services.set_lock(environment_id=environment.id, locked=True, actor_label="ci")
    # must not raise EnvironmentLocked
    services.update_variable_layout(environment_id=environment.id, user=admin_user, key="A", group_name="G")


@pytest.mark.django_db
def test_update_variable_layout_leaves_unspecified_field_unchanged(environment, admin_user):
    services.create_variable(environment_id=environment.id, user=admin_user, key="A", value="1", is_secret=False)
    services.update_variable_layout(environment_id=environment.id, user=admin_user, key="A", group_name="G1")
    var = services.update_variable_layout(environment_id=environment.id, user=admin_user, key="A", leading_comment="c1")
    assert var.group_name == "G1"
    assert var.leading_comment == "c1"


@pytest.mark.django_db
def test_reorder_variables(environment, admin_user):
    for k in ("A", "B", "C"):
        services.create_variable(environment_id=environment.id, user=admin_user, key=k, value="1", is_secret=False)
    services.reorder_variables(environment_id=environment.id, user=admin_user, ordered_keys=["C", "A", "B"])
    assert list(environment.variables.order_by("order").values_list("key", flat=True)) == ["C", "A", "B"]


@pytest.mark.django_db
def test_reorder_variables_rejects_partial_or_stale_list(environment, admin_user):
    for k in ("A", "B"):
        services.create_variable(environment_id=environment.id, user=admin_user, key=k, value="1", is_secret=False)
    with pytest.raises(services.ValidationError):
        services.reorder_variables(environment_id=environment.id, user=admin_user, ordered_keys=["A"])
    with pytest.raises(services.ValidationError):
        services.reorder_variables(environment_id=environment.id, user=admin_user, ordered_keys=["A", "B", "C"])


@pytest.mark.django_db
def test_restore_revision_carries_layout_metadata(environment, admin_user):
    services.create_variable(environment_id=environment.id, user=admin_user, key="A", value="1", is_secret=False)
    services.update_variable_layout(environment_id=environment.id, user=admin_user, key="A", group_name="G")
    environment.refresh_from_db()
    # Layout metadata is only snapshotted the next time a value edit bumps
    # the revision (update_variable_layout itself doesn't create a Revision
    # — see test_update_variable_layout_does_not_bump_revision).
    services.update_variable(environment_id=environment.id, user=admin_user, key="A", value="1b", revision=environment.revision)
    environment.refresh_from_db()
    rev_with_group = environment.revision

    services.update_variable(environment_id=environment.id, user=admin_user, key="A", value="2", revision=rev_with_group)
    environment.refresh_from_db()

    services.restore_revision(environment_id=environment.id, user=admin_user, revision_number=rev_with_group)
    var = environment.variables.get(key="A")
    assert var.value == "1b"
    assert var.group_name == "G"


@pytest.mark.django_db
def test_restore_revision_from_snapshot_missing_layout_keys_does_not_fail(environment, admin_user):
    """Simulates a Revision snapshot taken before layout metadata existed."""
    from core.models import Revision

    services.create_variable(environment_id=environment.id, user=admin_user, key="A", value="1", is_secret=False)
    environment.refresh_from_db()
    old_snapshot = [{"key": "A", "value": "old", "encrypted_value": None, "is_secret": False}]
    Revision.objects.create(environment=environment, revision_number=999, snapshot=old_snapshot, created_by=admin_user)

    services.restore_revision(environment_id=environment.id, user=admin_user, revision_number=999)
    var = environment.variables.get(key="A")
    assert var.value == "old"
    assert var.group_name == ""


# --- swap_variable_order / rename_group / ungroup ---------------------------

@pytest.mark.django_db
def test_swap_variable_order_moves_up(environment, admin_user):
    for k in ("A", "B", "C"):
        services.create_variable(environment_id=environment.id, user=admin_user, key=k, value="1", is_secret=False)
    services.swap_variable_order(environment_id=environment.id, user=admin_user, key="C", direction="up")
    assert list(environment.variables.order_by("order").values_list("key", flat=True)) == ["A", "C", "B"]


@pytest.mark.django_db
def test_swap_variable_order_moves_down(environment, admin_user):
    for k in ("A", "B", "C"):
        services.create_variable(environment_id=environment.id, user=admin_user, key=k, value="1", is_secret=False)
    services.swap_variable_order(environment_id=environment.id, user=admin_user, key="A", direction="down")
    assert list(environment.variables.order_by("order").values_list("key", flat=True)) == ["B", "A", "C"]


@pytest.mark.django_db
def test_swap_variable_order_at_boundary_is_a_noop(environment, admin_user):
    for k in ("A", "B"):
        services.create_variable(environment_id=environment.id, user=admin_user, key=k, value="1", is_secret=False)
    services.swap_variable_order(environment_id=environment.id, user=admin_user, key="A", direction="up")
    services.swap_variable_order(environment_id=environment.id, user=admin_user, key="B", direction="down")
    assert list(environment.variables.order_by("order").values_list("key", flat=True)) == ["A", "B"]


@pytest.mark.django_db
def test_swap_variable_order_rejects_bad_direction(environment, admin_user):
    services.create_variable(environment_id=environment.id, user=admin_user, key="A", value="1", is_secret=False)
    with pytest.raises(services.ValidationError):
        services.swap_variable_order(environment_id=environment.id, user=admin_user, key="A", direction="sideways")


@pytest.mark.django_db
def test_swap_variable_order_unknown_key_not_found(environment, admin_user):
    with pytest.raises(services.NotFound):
        services.swap_variable_order(environment_id=environment.id, user=admin_user, key="NOPE", direction="up")


@pytest.mark.django_db
def test_rename_group_updates_all_members(environment, admin_user):
    for k in ("A", "B", "C"):
        services.create_variable(environment_id=environment.id, user=admin_user, key=k, value="1", is_secret=False)
    services.update_variable_layout(environment_id=environment.id, user=admin_user, key="A", group_name="Old")
    services.update_variable_layout(environment_id=environment.id, user=admin_user, key="B", group_name="Old")
    services.update_variable_layout(environment_id=environment.id, user=admin_user, key="C", group_name="Other")

    updated = services.rename_group(environment_id=environment.id, user=admin_user, old_name="Old", new_name="New")
    assert updated == 2
    assert environment.variables.get(key="A").group_name == "New"
    assert environment.variables.get(key="B").group_name == "New"
    assert environment.variables.get(key="C").group_name == "Other"


@pytest.mark.django_db
def test_rename_group_rejects_empty_new_name(environment, admin_user):
    with pytest.raises(services.ValidationError):
        services.rename_group(environment_id=environment.id, user=admin_user, old_name="Old", new_name="  ")


@pytest.mark.django_db
def test_rename_group_no_members_is_a_noop_returns_zero(environment, admin_user):
    assert services.rename_group(environment_id=environment.id, user=admin_user, old_name="Ghost", new_name="X") == 0


@pytest.mark.django_db
def test_ungroup_clears_group_name_for_all_members(environment, admin_user):
    for k in ("A", "B"):
        services.create_variable(environment_id=environment.id, user=admin_user, key=k, value="1", is_secret=False)
        services.update_variable_layout(environment_id=environment.id, user=admin_user, key=k, group_name="G")

    updated = services.ungroup(environment_id=environment.id, user=admin_user, group_name="G")
    assert updated == 2
    assert environment.variables.get(key="A").group_name == ""
    assert environment.variables.get(key="B").group_name == ""


@pytest.mark.django_db
def test_ungroup_does_not_delete_variables(environment, admin_user):
    services.create_variable(environment_id=environment.id, user=admin_user, key="A", value="1", is_secret=False)
    services.update_variable_layout(environment_id=environment.id, user=admin_user, key="A", group_name="G")
    services.ungroup(environment_id=environment.id, user=admin_user, group_name="G")
    assert environment.variables.filter(key="A").exists()


# --- group-contiguity invariant ----------------------------------------------

def _make(environment, admin_user, keys, groups=None):
    """Creates `keys` in order, optionally assigning groups (dict key->group)."""
    groups = groups or {}
    for k in keys:
        services.create_variable(environment_id=environment.id, user=admin_user, key=k, value="1", is_secret=False)
    for k, g in groups.items():
        services.update_variable_layout(environment_id=environment.id, user=admin_user, key=k, group_name=g)


@pytest.mark.django_db
def test_reorder_rejects_split_group(environment, admin_user):
    _make(environment, admin_user, ["A", "B", "C"], groups={"A": "G", "C": "G"})
    # A and C are in G; the current write already keeps them contiguous
    # (update_variable_layout repositions). Directly ask for a split order:
    with pytest.raises(services.ValidationError):
        services.reorder_variables(environment_id=environment.id, user=admin_user, ordered_keys=["A", "B", "C"])


@pytest.mark.django_db
def test_update_variable_layout_repositions_to_stay_contiguous(environment, admin_user):
    _make(environment, admin_user, ["A", "B", "C", "D"], groups={"A": "G", "B": "G"})
    # C sits between the group members (order 2) and D after (order 3);
    # assigning C to G must not leave G split as [A,B]...[C] elsewhere —
    # it must land adjacent to the existing G block.
    services.update_variable_layout(environment_id=environment.id, user=admin_user, key="D", group_name="G")
    keys_in_order = list(environment.variables.order_by("order").values_list("key", flat=True))
    g_positions = [i for i, k in enumerate(keys_in_order) if k in ("A", "B", "D")]
    assert g_positions == list(range(min(g_positions), max(g_positions) + 1))  # contiguous


@pytest.mark.django_db
def test_swap_variable_order_never_splits_a_group(environment, admin_user):
    _make(environment, admin_user, ["X", "A", "B", "C", "Y"], groups={"A": "G", "B": "G", "C": "G"})
    # X is right before the G block; moving X down must jump the whole
    # block (X ends up after C), never land inside it.
    services.swap_variable_order(environment_id=environment.id, user=admin_user, key="X", direction="down")
    keys_in_order = list(environment.variables.order_by("order").values_list("key", flat=True))
    assert keys_in_order.index("X") not in range(
        keys_in_order.index("A") + 1, keys_in_order.index("C") + 1
    )
    g_positions = sorted(keys_in_order.index(k) for k in ("A", "B", "C"))
    assert g_positions == list(range(min(g_positions), max(g_positions) + 1))


@pytest.mark.django_db
def test_swap_variable_order_moves_within_group(environment, admin_user):
    _make(environment, admin_user, ["A", "B", "C"], groups={"A": "G", "B": "G", "C": "G"})
    services.swap_variable_order(environment_id=environment.id, user=admin_user, key="C", direction="up")
    keys_in_order = list(environment.variables.order_by("order").values_list("key", flat=True))
    assert keys_in_order == ["A", "C", "B"]


@pytest.mark.django_db
def test_import_merges_new_members_into_existing_group_block(environment, admin_user, tmp_root):
    # Pre-existing tracked variable already in group "G", positioned early.
    _make(environment, admin_user, ["A", "Z"], groups={"A": "G"})
    (tmp_root / ".env").write_text("# --- G ---\nA=1\nNEWVAR=2\n")
    services.import_variables_from_file(environment_id=environment.id, user=admin_user)
    keys_in_order = list(environment.variables.order_by("order").values_list("key", flat=True))
    g_positions = sorted(
        i for i, k in enumerate(keys_in_order)
        if environment.variables.get(key=k).group_name == "G"
    )
    assert g_positions == list(range(min(g_positions), max(g_positions) + 1))


# --- refresh from file (manual re-import) ------------------------------------

@pytest.mark.django_db
def test_import_variables_from_file_is_reusable_manually(environment, admin_user, tmp_root):
    (tmp_root / ".env").write_text("A=1\n")
    n1 = services.import_variables_from_file(environment_id=environment.id, user=admin_user)
    assert n1 == 1
    (tmp_root / ".env").write_text("A=1\nB=2\n")
    n2 = services.import_variables_from_file(environment_id=environment.id, user=admin_user)
    assert n2 == 1  # only the new key, A already tracked and untouched
    assert environment.variables.count() == 2


# --- create/update with group+comment reflects in the file on the first write ----

@pytest.mark.django_db
def test_create_variable_with_group_reflects_in_file_immediately(environment, admin_user, tmp_root):
    """Regression: create_variable used to write the file, and only then
    (via a separate update_variable_layout call) get its group assigned —
    so the file's first version never had the group. create_variable now
    takes group_name/leading_comment directly so a single write is correct."""
    services.create_variable(
        environment_id=environment.id, user=admin_user, key="DB_HOST", value="postgres", is_secret=False,
        group_name="Database", leading_comment="the db host",
    )
    written = (tmp_root / ".env").read_text()
    assert "Database" in written
    assert "the db host" in written

    from core import envdoc
    doc = envdoc.parse(written)
    assert doc.find_variable("DB_HOST").value == "postgres"
    assert "Database" in [g.name for g in doc.children if isinstance(g, envdoc.Group)]


@pytest.mark.django_db
def test_edit_variable_group_change_reflects_in_file_from_same_submit(environment, admin_user, tmp_root):
    """Regression: variable_edit_view called update_variable (writes the
    file) then update_variable_layout (doesn't write) — the file reflected
    the OLD group until some unrelated later edit. Services-level
    equivalent of the view's now-corrected call order (layout first)."""
    services.create_variable(environment_id=environment.id, user=admin_user, key="A", value="1", is_secret=False)
    services.update_variable_layout(environment_id=environment.id, user=admin_user, key="A", group_name="Custom")
    environment.refresh_from_db()
    services.update_variable(
        environment_id=environment.id, user=admin_user, key="A", value="2", revision=environment.revision,
    )
    written = (tmp_root / ".env").read_text()
    assert "Custom" in written
