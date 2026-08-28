import json

import pytest


def post(client, url, data):
    return client.post(url, data=json.dumps(data), content_type="application/json")


def patch(client, url, data):
    return client.patch(url, data=json.dumps(data), content_type="application/json")


@pytest.mark.django_db
class TestUpdateVariableLayout:
    def test_sets_group_and_comment(self, client, dev_read_write, environment):
        client.force_login(dev_read_write)
        post(client, f"/api/v1/environments/{environment.id}/variables", {"key": "A", "value": "1"})
        res = patch(client, f"/api/v1/environments/{environment.id}/variables/A/layout",
                    {"group": "Database", "comment": "the host"})
        assert res.status_code == 200
        body = res.json()["data"]
        assert body["group"] == "Database"
        assert body["comment"] == "the host"

    def test_requires_write_permission(self, client, dev_user, environment):
        from core.models import Permission
        Permission.objects.create(user=dev_user, environment=environment, can_read=True)
        client.force_login(dev_user)
        res = patch(client, f"/api/v1/environments/{environment.id}/variables/A/layout", {"group": "X"})
        assert res.status_code == 403

    def test_does_not_change_environment_revision(self, client, dev_read_write, environment):
        client.force_login(dev_read_write)
        post(client, f"/api/v1/environments/{environment.id}/variables", {"key": "A", "value": "1"})
        before = client.get(f"/api/v1/environments/{environment.id}/variables").json()["data"]["revision"]
        patch(client, f"/api/v1/environments/{environment.id}/variables/A/layout", {"group": "X"})
        after = client.get(f"/api/v1/environments/{environment.id}/variables").json()["data"]["revision"]
        assert before == after

    def test_allowed_while_locked_for_deploy(self, client, admin_user, dev_read_write, environment):
        from core import services
        client.force_login(dev_read_write)
        post(client, f"/api/v1/environments/{environment.id}/variables", {"key": "A", "value": "1"})
        services.set_lock(environment_id=environment.id, locked=True, actor_label="test")
        res = patch(client, f"/api/v1/environments/{environment.id}/variables/A/layout", {"group": "X"})
        assert res.status_code == 200

    def test_unknown_variable_is_not_found(self, client, dev_read_write, environment):
        client.force_login(dev_read_write)
        res = patch(client, f"/api/v1/environments/{environment.id}/variables/NOPE/layout", {"group": "X"})
        assert res.status_code == 404


@pytest.mark.django_db
class TestReorderVariables:
    def test_reorders(self, client, dev_read_write, environment):
        client.force_login(dev_read_write)
        for k in ("A", "B", "C"):
            post(client, f"/api/v1/environments/{environment.id}/variables", {"key": k, "value": "1"})
        res = post(client, f"/api/v1/environments/{environment.id}/variables/reorder", {"keys": ["C", "A", "B"]})
        assert res.status_code == 200
        assert [v["key"] for v in res.json()["data"]["variables"]] == ["C", "A", "B"]

    def test_rejects_partial_list(self, client, dev_read_write, environment):
        client.force_login(dev_read_write)
        for k in ("A", "B"):
            post(client, f"/api/v1/environments/{environment.id}/variables", {"key": k, "value": "1"})
        res = post(client, f"/api/v1/environments/{environment.id}/variables/reorder", {"keys": ["A"]})
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_requires_write_permission(self, client, dev_user, environment):
        from core.models import Permission
        Permission.objects.create(user=dev_user, environment=environment, can_read=True)
        client.force_login(dev_user)
        res = post(client, f"/api/v1/environments/{environment.id}/variables/reorder", {"keys": []})
        assert res.status_code == 403

    def test_route_does_not_collide_with_key_routes(self, client, dev_read_write, environment):
        """'reorder' must never be swallowed as a {key} path segment by
        another /variables/{key}/... route registered earlier."""
        client.force_login(dev_read_write)
        post(client, f"/api/v1/environments/{environment.id}/variables", {"key": "reorder", "value": "x"})
        res = post(client, f"/api/v1/environments/{environment.id}/variables/reorder", {"keys": ["reorder"]})
        assert res.status_code == 200
