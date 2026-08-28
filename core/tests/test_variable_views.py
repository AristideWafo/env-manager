import pytest


@pytest.mark.django_db
class TestVariableFormsSetLayout:
    def test_create_with_group_and_comment(self, client, dev_read_write, environment):
        client.force_login(dev_read_write)
        res = client.post(
            f"/environments/{environment.id}/variables/new/",
            {"key": "DB_HOST", "value": "postgres", "group": "Database", "comment": "the db host"},
        )
        assert res.status_code == 200
        var = environment.variables.get(key="DB_HOST")
        assert var.group_name == "Database"
        assert var.leading_comment == "the db host"

    def test_create_with_group_writes_it_to_file_on_first_submit(self, client, dev_read_write, environment, tmp_root):
        """Regression: the file used to be written before the group was
        assigned (two separate service calls) — group never made it in
        until an unrelated later edit."""
        client.force_login(dev_read_write)
        client.post(
            f"/environments/{environment.id}/variables/new/",
            {"key": "DB_HOST", "value": "postgres", "group": "Database", "comment": "the db host"},
        )
        written = (tmp_root / ".env").read_text()
        assert "Database" in written
        assert "the db host" in written

    def test_create_without_group_or_comment_leaves_them_blank(self, client, dev_read_write, environment):
        client.force_login(dev_read_write)
        client.post(f"/environments/{environment.id}/variables/new/", {"key": "A", "value": "1"})
        var = environment.variables.get(key="A")
        assert var.group_name == ""
        assert var.leading_comment == ""

    def test_edit_updates_group_and_comment(self, client, dev_read_write, environment):
        from core import services
        client.force_login(dev_read_write)
        services.create_variable(environment_id=environment.id, user=dev_read_write, key="A", value="1", is_secret=False)
        environment.refresh_from_db()
        res = client.post(
            f"/environments/{environment.id}/variables/A/edit/",
            {"value": "1", "revision": environment.revision, "group": "Custom", "comment": "note"},
        )
        assert res.status_code == 200
        var = environment.variables.get(key="A")
        assert var.group_name == "Custom"
        assert var.leading_comment == "note"

    def test_edit_group_change_writes_it_to_file_on_same_submit(self, client, dev_read_write, environment, tmp_root):
        """Regression: update_variable (writes the file) used to run before
        update_variable_layout (doesn't write) — the file kept the OLD
        group until an unrelated later edit."""
        from core import services
        client.force_login(dev_read_write)
        services.create_variable(environment_id=environment.id, user=dev_read_write, key="A", value="1", is_secret=False)
        environment.refresh_from_db()
        client.post(
            f"/environments/{environment.id}/variables/A/edit/",
            {"value": "1", "revision": environment.revision, "group": "Custom", "comment": "note"},
        )
        written = (tmp_root / ".env").read_text()
        assert "Custom" in written
        assert "note" in written

    def test_edit_clearing_the_field_clears_it_on_the_variable(self, client, dev_read_write, environment):
        from core import services
        client.force_login(dev_read_write)
        services.create_variable(environment_id=environment.id, user=dev_read_write, key="A", value="1", is_secret=False)
        services.update_variable_layout(environment_id=environment.id, user=dev_read_write, key="A", group_name="G", leading_comment="c")
        environment.refresh_from_db()
        client.post(
            f"/environments/{environment.id}/variables/A/edit/",
            {"value": "1", "revision": environment.revision, "group": "", "comment": ""},
        )
        var = environment.variables.get(key="A")
        assert var.group_name == ""
        assert var.leading_comment == ""


@pytest.mark.django_db
class TestVariablesTableFragmentRendersGroupedTable:
    """Asserts against the _variables_table.html fragment (returned by the
    edit/delete/create endpoints), not the full environment.html page —
    the full page pulls in base.html's {% static %} asset pipeline, which
    needs `collectstatic` to have run and isn't exercised by other tests."""

    def test_group_header_and_comment_rendered(self, client, dev_read_write, environment):
        from core import services
        client.force_login(dev_read_write)
        services.create_variable(environment_id=environment.id, user=dev_read_write, key="DB_HOST", value="postgres", is_secret=False)
        services.update_variable_layout(
            environment_id=environment.id, user=dev_read_write, key="DB_HOST",
            group_name="Database", leading_comment="the db host",
        )
        environment.refresh_from_db()
        res = client.post(
            f"/environments/{environment.id}/variables/DB_HOST/edit/",
            {"value": "postgres", "revision": environment.revision, "group": "Database", "comment": "the db host"},
        )
        html = res.content.decode()
        assert "Database" in html
        assert "the db host" in html

    def test_variables_ordered_by_order_field_not_key(self, client, dev_read_write, environment):
        from core import services
        client.force_login(dev_read_write)
        services.create_variable(environment_id=environment.id, user=dev_read_write, key="ZZZ", value="1", is_secret=False)
        services.create_variable(environment_id=environment.id, user=dev_read_write, key="AAA", value="1", is_secret=False)
        environment.refresh_from_db()
        res = client.post(
            f"/environments/{environment.id}/variables/AAA/edit/",
            {"value": "1", "revision": environment.revision},
        )
        html = res.content.decode()
        assert html.index("ZZZ") < html.index("AAA")  # created first -> lower order -> listed first


@pytest.mark.django_db
class TestVariableMoveView:
    def test_move_up_reorders(self, client, dev_read_write, environment):
        from core import services
        client.force_login(dev_read_write)
        services.create_variable(environment_id=environment.id, user=dev_read_write, key="A", value="1", is_secret=False)
        services.create_variable(environment_id=environment.id, user=dev_read_write, key="B", value="1", is_secret=False)
        res = client.post(f"/environments/{environment.id}/variables/B/move/up/")
        assert res.status_code == 200
        html = res.content.decode()
        assert html.index("B") < html.index("A")

    def test_requires_write_permission(self, client, dev_user, environment):
        from core.models import Permission
        Permission.objects.create(user=dev_user, environment=environment, can_read=True)
        client.force_login(dev_user)
        res = client.post(f"/environments/{environment.id}/variables/A/move/up/")
        assert res.status_code == 403


@pytest.mark.django_db
class TestGroupRenameUngroupViews:
    def test_rename_group_via_hx_prompt_header(self, client, dev_read_write, environment):
        from core import services
        client.force_login(dev_read_write)
        services.create_variable(environment_id=environment.id, user=dev_read_write, key="A", value="1", is_secret=False)
        services.update_variable_layout(environment_id=environment.id, user=dev_read_write, key="A", group_name="Old")
        res = client.post(f"/environments/{environment.id}/groups/rename/", {"group_name": "Old"}, HTTP_HX_PROMPT="New")
        assert res.status_code == 200
        assert environment.variables.get(key="A").group_name == "New"
        assert "New" in res.content.decode()

    def test_rename_group_with_slash_in_name(self, client, dev_read_write, environment):
        """Regression: a group_name containing '/' (e.g. a real "Traefik /
        TLS" header) used to be embedded in the URL path, which a
        <str:group_name> segment can never match — 500 NoReverseMatch on
        every action touching that group. group_name now travels in the
        POST body instead."""
        from core import services
        client.force_login(dev_read_write)
        services.create_variable(environment_id=environment.id, user=dev_read_write, key="A", value="1", is_secret=False)
        services.update_variable_layout(environment_id=environment.id, user=dev_read_write, key="A", group_name="Traefik / TLS")
        res = client.post(f"/environments/{environment.id}/groups/rename/", {"group_name": "Traefik / TLS"}, HTTP_HX_PROMPT="New")
        assert res.status_code == 200
        assert environment.variables.get(key="A").group_name == "New"

    def test_ungroup_clears_group(self, client, dev_read_write, environment):
        from core import services
        client.force_login(dev_read_write)
        services.create_variable(environment_id=environment.id, user=dev_read_write, key="A", value="1", is_secret=False)
        services.update_variable_layout(environment_id=environment.id, user=dev_read_write, key="A", group_name="Old")
        res = client.post(f"/environments/{environment.id}/groups/ungroup/", {"group_name": "Old"})
        assert res.status_code == 200
        assert environment.variables.get(key="A").group_name == ""

    def test_ungroup_group_with_slash_in_name(self, client, dev_read_write, environment):
        from core import services
        client.force_login(dev_read_write)
        services.create_variable(environment_id=environment.id, user=dev_read_write, key="A", value="1", is_secret=False)
        services.update_variable_layout(environment_id=environment.id, user=dev_read_write, key="A", group_name="Traefik / TLS")
        res = client.post(f"/environments/{environment.id}/groups/ungroup/", {"group_name": "Traefik / TLS"})
        assert res.status_code == 200
        assert environment.variables.get(key="A").group_name == ""

    def test_rename_requires_write_permission(self, client, dev_user, environment):
        from core.models import Permission
        Permission.objects.create(user=dev_user, environment=environment, can_read=True)
        client.force_login(dev_user)
        res = client.post(f"/environments/{environment.id}/groups/rename/", {"group_name": "Old"}, HTTP_HX_PROMPT="New")
        assert res.status_code == 403


@pytest.mark.django_db
class TestEnvironmentFullPageRender:
    """Exercises environment_view's actual GET response (not just the HTMX
    fragment) — needs `collectstatic` to have run for base.html's
    {% static %} tags (see .github/workflows/ci.yml)."""

    def test_renders_200_with_grouped_variables(self, client, dev_read_write, environment):
        from core import services
        client.force_login(dev_read_write)
        services.create_variable(environment_id=environment.id, user=dev_read_write, key="DB_HOST", value="postgres", is_secret=False)
        services.update_variable_layout(
            environment_id=environment.id, user=dev_read_write, key="DB_HOST",
            group_name="Database", leading_comment="the db host",
        )
        res = client.get(f"/environments/{environment.id}/")
        assert res.status_code == 200
        html = res.content.decode()
        assert "Database" in html
        assert "the db host" in html
        assert "DB_HOST" in html

    def test_renders_200_when_empty(self, client, dev_read_write, environment):
        client.force_login(dev_read_write)
        res = client.get(f"/environments/{environment.id}/")
        assert res.status_code == 200

    def test_forbidden_without_read_permission(self, client, dev_user, environment):
        client.force_login(dev_user)
        res = client.get(f"/environments/{environment.id}/")
        assert res.status_code == 403


@pytest.mark.django_db
class TestEnvironmentRefreshView:
    def test_imports_new_keys_and_rerenders_table(self, client, dev_read_write, environment, tmp_root):
        client.force_login(dev_read_write)
        (tmp_root / ".env").write_text("A=1\nB=2\n")
        res = client.post(f"/environments/{environment.id}/refresh/")
        assert res.status_code == 200
        assert environment.variables.count() == 2
        assert "A" in res.content.decode()

    def test_refresh_with_slash_in_group_name_from_real_file_does_not_500(self, client, dev_read_write, environment, tmp_root):
        """Exact reproduction of the reported production crash: importing
        (and then rendering the table for) a real .env file whose group
        header contains '/' — e.g. "# ==== Traefik / TLS ====" — used to
        NoReverseMatch on the group's Rename/Ungroup buttons."""
        client.force_login(dev_read_write)
        (tmp_root / ".env").write_text("# ==================== Traefik / TLS ====================\nENVIRONMENT=dev\n")
        res = client.post(f"/environments/{environment.id}/refresh/")
        assert res.status_code == 200
        assert "Traefik / TLS" in res.content.decode()

    def test_overwrites_tracked_value_from_disk(self, client, dev_read_write, environment, tmp_root):
        from core import services
        client.force_login(dev_read_write)
        services.create_variable(environment_id=environment.id, user=dev_read_write, key="A", value="from-db", is_secret=False)
        (tmp_root / ".env").write_text("A=from-disk\n")
        client.post(f"/environments/{environment.id}/refresh/")
        assert environment.variables.get(key="A").value == "from-disk"

    def test_requires_write_permission(self, client, dev_user, environment):
        from core.models import Permission
        Permission.objects.create(user=dev_user, environment=environment, can_read=True)
        client.force_login(dev_user)
        res = client.post(f"/environments/{environment.id}/refresh/")
        assert res.status_code == 403
