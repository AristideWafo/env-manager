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
def test_import_does_not_change_written_file_format(environment, admin_user, tmp_root):
    """The structural metadata captured on import must never leak into
    write_environment_file's output — that stays the canonical
    always-quoted, alphabetically-sorted format regardless of import."""
    (tmp_root / ".env").write_text(FIXTURE.read_text())
    services.import_variables_from_file(environment_id=environment.id, user=admin_user)
    services.create_variable(environment_id=environment.id, user=admin_user, key="ZZZ", value="1", is_secret=False)
    written = (tmp_root / ".env").read_text()
    lines = [ln for ln in written.splitlines() if ln]
    keys = [ln.split("=", 1)[0] for ln in lines]
    assert keys == sorted(keys)  # still alphabetical
    assert all(ln.split("=", 1)[1].startswith('"') for ln in lines)  # still always-quoted
    assert "---" not in written and "#" not in written  # groups/comments never written


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
