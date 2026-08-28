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
