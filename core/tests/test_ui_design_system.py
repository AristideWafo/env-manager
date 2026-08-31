from pathlib import Path

import pytest
from django.conf import settings


def test_theme_uses_the_documented_font_families():
    css = (Path(settings.BASE_DIR) / "static/css/theme.css").read_text()
    assert '--font-sans: "Inter"' in css
    assert '--font-mono: "JetBrains Mono"' in css


def test_auth_shell_loads_shared_fonts_and_ui_components(client):
    body = client.get("/login/").content.decode()
    assert "family=Inter" in body
    assert "family=JetBrains+Mono" in body
    assert "static/css/theme.css" in body
    assert "static/js/ui.js" in body
    assert 'class="card auth-panel"' in body
    assert 'id="login-form"' in body


@pytest.mark.django_db
def test_dashboard_uses_active_navigation_and_row_components(client, dev_read_write):
    client.force_login(dev_read_write)
    body = client.get("/").content.decode()
    assert 'class="nav-link is-active"' in body
    assert 'aria-current="page"' in body
    assert 'class="row-list"' in body
    assert 'class="row-list-item"' in body


@pytest.mark.django_db
def test_locked_environment_uses_warning_component(client, dev_read_write, environment):
    environment.locked_for_deploy = True
    environment.save(update_fields=["locked_for_deploy"])
    client.force_login(dev_read_write)
    body = client.get(f"/environments/{environment.id}/").content.decode()
    assert "alert-warning" in body
    assert "locked for deploy" in body


@pytest.mark.django_db
def test_variable_form_uses_accessible_reusable_field_components(client, dev_read_write, environment):
    client.force_login(dev_read_write)
    body = client.get(f"/environments/{environment.id}/variables/new/").content.decode()
    assert 'class="inline-editor space-y-3"' in body
    assert 'for="variable-key"' in body
    assert 'id="variable-key"' in body
    assert 'class="field-checkbox"' in body
