"""
CSS/layout regressions reported by the user (2026-08-28):
- main content was centered (max-w-5xl mx-auto) leaving a "ghost gap" +
  the card's own left border reading as a second vertical divider between
  the sidebar and the content.
- the variables table used the browser's default auto column layout, so
  one long value in any row widened the Value column for every row,
  leaving a visible gap after short values and destabilizing the
  Key/Actions columns.

These are template-content assertions (not pixel tests) — they just lock
in the specific classes the fix relies on so a future edit can't silently
reintroduce the old behavior.
"""

import pytest


@pytest.mark.django_db
def test_main_content_is_not_centered_away_from_sidebar(client, dev_user, environment):
    from core.models import Permission

    Permission.objects.create(user=dev_user, environment=environment, can_read=True)
    client.force_login(dev_user)
    res = client.get(f"/environments/{environment.id}/")
    body = res.content.decode()
    assert "mx-auto" not in body.split("<main", 1)[1].split(">", 1)[0]
    assert "max-w-5xl" not in body


@pytest.mark.django_db
def test_variables_table_uses_fixed_column_layout(client, dev_read_write, environment):
    from core import services

    services.create_variable(environment_id=environment.id, user=dev_read_write, key="A", value="1", is_secret=False)
    client.force_login(dev_read_write)
    res = client.get(f"/environments/{environment.id}/")
    body = res.content.decode()
    assert "table-fixed" in body
    assert "<colgroup>" in body
