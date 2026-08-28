import pytest
from freezegun import freeze_time

from core.webauthn_service import (
    INVITATION_MAX_AGE,
    make_invitation_token,
    resolve_invitation_token,
)


@pytest.mark.django_db
def test_invitation_token_round_trips_to_the_same_user(dev_user):
    token = make_invitation_token(dev_user)
    resolved = resolve_invitation_token(token)
    assert resolved.id == dev_user.id


@pytest.mark.django_db
def test_invitation_token_rejects_inactive_user(dev_user):
    token = make_invitation_token(dev_user)
    dev_user.is_active = False
    dev_user.save()
    with pytest.raises(ValueError):
        resolve_invitation_token(token)


@pytest.mark.django_db
def test_invitation_token_expires(dev_user):
    with freeze_time("2020-01-01"):
        token = make_invitation_token(dev_user)
    with freeze_time("2020-01-01") as frozen:
        frozen.tick(delta=INVITATION_MAX_AGE + 60)
        with pytest.raises(ValueError):
            resolve_invitation_token(token)
