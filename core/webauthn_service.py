"""
WebAuthn (passkey) registration & login ceremonies (UC-01, UC-02, UC-05).

Invitation model: rather than adding an invitation-token column (not in
DATA_MODEL.md), we use Django's TimestampSigner to mint a short-lived signed
token embedding the user id whenever an ADMIN creates a user (UC-03) or adds a
recovery credential slot (UC-05). The token is the only proof needed to run a
registration ceremony for that user — treat it like a password-reset link.
"""

from __future__ import annotations

import base64

from django.conf import settings
from django.core import signing
from django.core.signing import BadSignature, SignatureExpired
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    UserVerificationRequirement,
)

from .models import Credential, User

INVITATION_SALT = "env-manager-webauthn-invitation"
INVITATION_MAX_AGE = 7 * 24 * 3600  # 7 days


def make_invitation_token(user: User) -> str:
    return signing.TimestampSigner(salt=INVITATION_SALT).sign(str(user.id))


def resolve_invitation_token(token: str) -> User:
    try:
        user_id = signing.TimestampSigner(salt=INVITATION_SALT).unsign(token, max_age=INVITATION_MAX_AGE)
    except SignatureExpired:
        raise ValueError("invitation token expired")
    except BadSignature:
        raise ValueError("invalid invitation token")
    try:
        return User.objects.get(id=user_id, is_active=True)
    except User.DoesNotExist:
        raise ValueError("invitation refers to an unknown or inactive user")


def registration_options(user: User) -> dict:
    options = generate_registration_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        rp_name=settings.WEBAUTHN_RP_NAME,
        user_id=str(user.id).encode(),
        user_name=user.email,
        user_display_name=user.display_name or user.email,
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=bytes(c.credential_id))
            for c in user.credentials.filter(status=Credential.Status.ACTIVE)
        ],
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
        supported_pub_key_algs=[COSEAlgorithmIdentifier.ECDSA_SHA_256, COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256],
    )
    return {"json": options_to_json(options), "challenge": base64.b64encode(options.challenge).decode()}


def verify_registration(*, user: User, credential_json: dict, expected_challenge_b64: str, device_label: str = ""):
    expected_challenge = base64.b64decode(expected_challenge_b64)
    verification = verify_registration_response(
        credential=credential_json,
        expected_challenge=expected_challenge,
        expected_rp_id=settings.WEBAUTHN_RP_ID,
        expected_origin=settings.WEBAUTHN_ORIGIN,
    )
    Credential.objects.create(
        user=user,
        credential_id=verification.credential_id,
        public_key=verification.credential_public_key,
        sign_count=verification.sign_count,
        device_label=device_label,
        status=Credential.Status.ACTIVE,
    )


def login_options(user: User) -> dict:
    creds = list(user.credentials.filter(status=Credential.Status.ACTIVE))
    options = generate_authentication_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        allow_credentials=[PublicKeyCredentialDescriptor(id=bytes(c.credential_id)) for c in creds],
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    return {"json": options_to_json(options), "challenge": base64.b64encode(options.challenge).decode()}


def verify_login(*, user: User, credential_json: dict, expected_challenge_b64: str) -> Credential:
    from webauthn.helpers import base64url_to_bytes

    expected_challenge = base64.b64decode(expected_challenge_b64)
    raw_id = base64url_to_bytes(credential_json["rawId"])
    try:
        credential = user.credentials.get(credential_id=raw_id, status=Credential.Status.ACTIVE)
    except Credential.DoesNotExist:
        raise ValueError("unknown credential")

    verification = verify_authentication_response(
        credential=credential_json,
        expected_challenge=expected_challenge,
        expected_rp_id=settings.WEBAUTHN_RP_ID,
        expected_origin=settings.WEBAUTHN_ORIGIN,
        credential_public_key=bytes(credential.public_key),
        credential_current_sign_count=credential.sign_count,
    )
    credential.sign_count = verification.new_sign_count
    from django.utils import timezone
    credential.last_used_at = timezone.now()
    credential.save(update_fields=["sign_count", "last_used_at"])
    return credential
