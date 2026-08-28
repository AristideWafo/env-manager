import json

import pytest

from core.models import AuditLog


@pytest.mark.django_db
def test_lock_requires_bearer_token(client, environment):
    res = client.post(f"/api/v1/environments/{environment.id}/lock")
    assert res.status_code == 401


@pytest.mark.django_db
def test_lock_and_unlock_with_valid_token(client, environment, settings):
    settings.CI_API_TOKENS = ["secret-ci-token"]
    headers = {"HTTP_AUTHORIZATION": "Bearer secret-ci-token"}
    res = client.post(f"/api/v1/environments/{environment.id}/lock", **headers)
    assert res.status_code == 200
    environment.refresh_from_db()
    assert environment.locked_for_deploy is True

    res = client.post(f"/api/v1/environments/{environment.id}/unlock", **headers)
    assert res.status_code == 200
    environment.refresh_from_db()
    assert environment.locked_for_deploy is False


@pytest.mark.django_db
def test_secret_value_never_appears_in_audit_log(client, dev_read_write, environment):
    client.force_login(dev_read_write)
    client.post(f"/api/v1/environments/{environment.id}/variables",
                data=json.dumps({"key": "TOKEN", "value": "super-secret-value", "is_secret": True}),
                content_type="application/json")
    for log in AuditLog.objects.all():
        blob = json.dumps({"target": log.target, "detail": log.detail})
        assert "super-secret-value" not in blob
