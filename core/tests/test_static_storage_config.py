"""
Regression coverage for the static-storage/DEBUG interaction that broke
production logins: `docker build` runs `collectstatic` with none of
docker-compose's runtime env vars set (DJANGO_DEBUG included), so tying the
staticfiles storage class directly to DEBUG meant collectstatic ran with
the plain (non-manifest) backend at build time, while the container then
started with DJANGO_DEBUG=0 at runtime expecting a manifest that was never
written — every {% static %} tag 500'd.

Settings.py's STORAGES dict is computed once at module-import time, so this
has to be checked out-of-process with controlled env vars rather than via
Django's `override_settings` (that only patches the already-imported value,
it can't re-run the import-time logic).
"""

import os
import subprocess
import sys

PROBE = (
    "import django, os; "
    "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); "
    "django.setup(); "
    "from django.conf import settings; "
    "print(settings.STORAGES['staticfiles']['BACKEND'])"
)

MANIFEST_BACKEND = "whitenoise.storage.CompressedManifestStaticFilesStorage"
PLAIN_BACKEND = "django.contrib.staticfiles.storage.StaticFilesStorage"


def _resolved_backend(env_overrides: dict) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("DJANGO_") and k != "ENV_MANAGER_FERNET_KEY"}
    env["ENV_MANAGER_FERNET_KEY"] = "Cw6yv1uP1i7GfE7dOEXaeYnLTr2C6VqcQha8y_5B1zA="
    env.update(env_overrides)
    result = subprocess.run(
        [sys.executable, "-c", PROBE], capture_output=True, text=True, env=env, check=True,
    )
    return result.stdout.strip()


def test_build_time_conditions_use_manifest_storage():
    """No DJANGO_DEBUG at all (like `docker build`, before docker-compose
    injects anything) + DJANGO_STATIC_MANIFEST=1 (set by the Dockerfile
    right before its collectstatic RUN) -> manifest backend, so collectstatic
    actually writes staticfiles.json."""
    assert _resolved_backend({"DJANGO_STATIC_MANIFEST": "1"}) == MANIFEST_BACKEND


def test_runtime_debug_off_uses_manifest_storage_even_without_the_flag():
    """Real production runtime (docker-compose sets DJANGO_DEBUG=0) must
    resolve to the same backend collectstatic built the manifest with,
    even without DJANGO_STATIC_MANIFEST explicitly set."""
    assert _resolved_backend({"DJANGO_DEBUG": "0"}) == MANIFEST_BACKEND


def test_local_dev_default_uses_plain_storage():
    """No env at all (bare `manage.py runserver` / test suite) must NOT
    require collectstatic to have run."""
    assert _resolved_backend({}) == PLAIN_BACKEND


def test_debug_on_without_manifest_flag_uses_plain_storage():
    assert _resolved_backend({"DJANGO_DEBUG": "1"}) == PLAIN_BACKEND
