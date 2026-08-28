"""
10-minute idle auto-logout: server-side rolling session expiry
(SESSION_COOKIE_AGE + SESSION_SAVE_EVERY_REQUEST in settings.py) plus the
client-side idle timer rendered into every authenticated page
(templates/cotton/layouts/app.html).
"""

import pytest
from django.conf import settings


def test_session_expires_after_ten_minutes_of_idle():
    assert settings.SESSION_COOKIE_AGE == 600


def test_session_age_is_rolling_not_fixed():
    """Without this, SESSION_COOKIE_AGE only counts from login — an active
    user would still get logged out mid-session at the 10-minute mark."""
    assert settings.SESSION_SAVE_EVERY_REQUEST is True


@pytest.mark.django_db
def test_authenticated_page_renders_client_side_idle_timer(client, dev_user, environment):
    from core.models import Permission

    Permission.objects.create(user=dev_user, environment=environment, can_read=True)
    client.force_login(dev_user)
    res = client.get(f"/environments/{environment.id}/")
    body = res.content.decode()
    assert "IDLE_MS" in body
    assert "core:logout" not in body  # {% url %} must have resolved, not leaked the tag
    assert "/logout/" in body or "logout" in body.lower()
