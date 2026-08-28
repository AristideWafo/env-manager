import json

import pytest

from core.models import Permission


def post(client, url, data):
    return client.post(url, data=json.dumps(data), content_type="application/json")


def patch(client, url, data):
    return client.patch(url, data=json.dumps(data), content_type="application/json")


def delete(client, url, data):
    return client.delete(url, data=json.dumps(data), content_type="application/json")


@pytest.mark.django_db
class TestPermissionEnforcement:
    def test_read_without_permission_is_forbidden(self, client, dev_user, environment):
        client.force_login(dev_user)
        res = client.get(f"/api/v1/environments/{environment.id}/variables")
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "FORBIDDEN"

    def test_write_without_permission_is_forbidden(self, client, dev_user, environment):
        Permission.objects.create(user=dev_user, environment=environment, can_read=True)
        client.force_login(dev_user)
        res = post(client, f"/api/v1/environments/{environment.id}/variables", {"key": "A", "value": "1"})
        assert res.status_code == 403

    def test_admin_bypasses_permission_grants(self, client, admin_user, environment):
        client.force_login(admin_user)
        res = client.get(f"/api/v1/environments/{environment.id}/variables")
        assert res.status_code == 200


@pytest.mark.django_db
class TestSecretMasking:
    def test_secret_value_is_masked_on_list(self, client, dev_read_write, environment):
        client.force_login(dev_read_write)
        post(client, f"/api/v1/environments/{environment.id}/variables",
             {"key": "PASSWORD", "value": "s3cret", "is_secret": True})
        res = client.get(f"/api/v1/environments/{environment.id}/variables")
        var = next(v for v in res.json()["data"]["variables"] if v["key"] == "PASSWORD")
        assert var["secret"] is True
        assert var["value"] is None

    def test_reveal_requires_explicit_confirm(self, client, dev_read_write, environment):
        client.force_login(dev_read_write)
        post(client, f"/api/v1/environments/{environment.id}/variables",
             {"key": "PASSWORD", "value": "s3cret", "is_secret": True})
        res = post(client, f"/api/v1/environments/{environment.id}/variables/PASSWORD/reveal", {"confirm": False})
        assert res.status_code == 422
        res = post(client, f"/api/v1/environments/{environment.id}/variables/PASSWORD/reveal", {"confirm": True})
        assert res.status_code == 200
        assert res.json()["data"]["value"] == "s3cret"

    def test_corrupt_secret_row_does_not_break_the_env_file_write(self, client, dev_read_write, environment):
        """A Variable with is_secret=True but no encrypted_value (only reachable
        by writing to the DB outside this app's own code paths) must not brick
        every future write to the environment."""
        from core.models import Variable
        Variable.objects.create(environment=environment, key="CORRUPT", is_secret=True, encrypted_value=None)
        client.force_login(dev_read_write)
        res = post(client, f"/api/v1/environments/{environment.id}/variables", {"key": "OK", "value": "1"})
        assert res.status_code == 200


@pytest.mark.django_db
class TestRevisionConflict:
    def test_stale_revision_is_rejected(self, client, dev_read_write, environment):
        client.force_login(dev_read_write)
        post(client, f"/api/v1/environments/{environment.id}/variables", {"key": "A", "value": "1"})
        environment.refresh_from_db()
        stale = environment.revision - 1 if environment.revision > 0 else 0
        res = patch(client, f"/api/v1/environments/{environment.id}/variables/A",
                    {"value": "2", "revision": stale})
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "REVISION_CONFLICT"

    def test_matching_revision_succeeds(self, client, dev_read_write, environment):
        client.force_login(dev_read_write)
        post(client, f"/api/v1/environments/{environment.id}/variables", {"key": "A", "value": "1"})
        environment.refresh_from_db()
        res = patch(client, f"/api/v1/environments/{environment.id}/variables/A",
                    {"value": "2", "revision": environment.revision})
        assert res.status_code == 200


@pytest.mark.django_db
class TestLockedEnvironment:
    def test_write_rejected_when_locked(self, client, dev_read_write, environment):
        environment.locked_for_deploy = True
        environment.save()
        client.force_login(dev_read_write)
        res = post(client, f"/api/v1/environments/{environment.id}/variables", {"key": "A", "value": "1"})
        assert res.status_code == 423
        assert res.json()["error"]["code"] == "ENVIRONMENT_LOCKED"


@pytest.mark.django_db
class TestMarkVariableSecret:
    def test_patch_can_flip_variable_to_secret(self, client, dev_read_write, environment):
        client.force_login(dev_read_write)
        post(client, f"/api/v1/environments/{environment.id}/variables", {"key": "A", "value": "1"})
        environment.refresh_from_db()
        res = patch(client, f"/api/v1/environments/{environment.id}/variables/A",
                    {"value": "1", "revision": environment.revision, "is_secret": True})
        assert res.status_code == 200
        assert res.json()["data"]["secret"] is True
        assert res.json()["data"]["value"] is None

    def test_patch_without_is_secret_keeps_current_flag(self, client, dev_read_write, environment):
        client.force_login(dev_read_write)
        post(client, f"/api/v1/environments/{environment.id}/variables",
             {"key": "A", "value": "1", "is_secret": True})
        environment.refresh_from_db()
        res = patch(client, f"/api/v1/environments/{environment.id}/variables/A",
                    {"value": "2", "revision": environment.revision})
        assert res.status_code == 200
        assert res.json()["data"]["secret"] is True


@pytest.mark.django_db
class TestKeyValidation:
    def test_invalid_key_rejected_on_create(self, client, dev_read_write, environment):
        client.force_login(dev_read_write)
        res = post(client, f"/api/v1/environments/{environment.id}/variables",
                    {"key": "not a valid key!", "value": "1"})
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_invalid_key_rejected_in_batch_create(self, client, dev_read_write, environment):
        client.force_login(dev_read_write)
        environment.refresh_from_db()
        res = post(client, f"/api/v1/environments/{environment.id}/variables/batch", {
            "revision": environment.revision,
            "operations": [{"op": "create", "key": "bad key", "value": "1"}],
        })
        assert res.status_code == 422
        # nothing written (all-or-nothing)
        assert environment.variables.count() == 0


@pytest.mark.django_db
class TestBatchAllOrNothing:
    def test_batch_fails_entirely_on_bad_op(self, client, dev_read_write, environment):
        client.force_login(dev_read_write)
        post(client, f"/api/v1/environments/{environment.id}/variables", {"key": "EXISTING", "value": "1"})
        environment.refresh_from_db()
        rev = environment.revision
        res = post(client, f"/api/v1/environments/{environment.id}/variables/batch", {
            "revision": rev,
            "operations": [
                {"op": "create", "key": "NEW", "value": "x"},
                {"op": "create", "key": "EXISTING", "value": "dup"},  # invalid: already exists
            ],
        })
        assert res.status_code == 422
        # nothing from the batch should have been written
        res2 = client.get(f"/api/v1/environments/{environment.id}/variables")
        keys = {v["key"] for v in res2.json()["data"]["variables"]}
        assert "NEW" not in keys
        environment.refresh_from_db()
        assert environment.revision == rev  # unchanged

    def test_batch_success_bumps_revision_once(self, client, dev_read_write, environment):
        client.force_login(dev_read_write)
        environment.refresh_from_db()
        rev = environment.revision
        res = post(client, f"/api/v1/environments/{environment.id}/variables/batch", {
            "revision": rev,
            "operations": [
                {"op": "create", "key": "A", "value": "1"},
                {"op": "create", "key": "B", "value": "2", "is_secret": True},
            ],
        })
        assert res.status_code == 200
        assert res.json()["data"]["revision"] == rev + 1
