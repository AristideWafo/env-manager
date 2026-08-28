"""
Django settings for Env Manager.
See AGENT_CONTEXT.md / DATA_MODEL.md / API_CONTRACT.md at repo root for the spec this implements.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Core / security -------------------------------------------------------

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-secret-key-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h]

# Set this if the app is served behind a reverse proxy that mounts it under a
# path prefix (e.g. Traefik PathPrefix("/env-management") + stripprefix
# middleware). Django's routing still sees the stripped path, but this makes
# every URL Django generates itself (redirects, {% url %}, static files) come
# back with the external prefix included, so navigation doesn't fall outside
# the proxy's routing rule. Leave unset when served at the domain root.
FORCE_SCRIPT_NAME = os.environ.get("DJANGO_FORCE_SCRIPT_NAME") or None

# Fernet key used to encrypt Variable.encrypted_value. Must live OUTSIDE the DB
# (AGENT_CONTEXT.md §5/§8-2). You can set ENV_MANAGER_FERNET_KEY explicitly (e.g.
# from a secret manager). If you don't, and DEBUG is off, one is generated on
# first boot and persisted next to the SQLite file (same data volume), so it
# survives restarts without any external variable to manage — just make sure
# that volume/directory is backed up: losing the key makes every stored secret
# permanently unrecoverable.
FERNET_KEY = os.environ.get("ENV_MANAGER_FERNET_KEY")
if not FERNET_KEY:
    if DEBUG:
        # Deterministic dev-only key so migrations/tests don't need external setup.
        FERNET_KEY = "Cw6yv1uP1i7GfE7dOEXaeYnLTr2C6VqcQha8y_5B1zA="
    else:
        from cryptography.fernet import Fernet

        _db_path = Path(os.environ.get("ENV_MANAGER_DB_PATH", BASE_DIR / "db.sqlite3"))
        _key_path = _db_path.parent / ".env_manager_fernet_key"
        if _key_path.exists():
            FERNET_KEY = _key_path.read_text().strip()
        else:
            _key_path.parent.mkdir(parents=True, exist_ok=True)
            FERNET_KEY = Fernet.generate_key().decode()
            _key_path.write_text(FERNET_KEY)
            _key_path.chmod(0o600)

# Roots the app is allowed to write .env files under. Declared here as a safety
# net (defense in depth); the authoritative list is the AllowedRoot table.
ENV_MANAGER_FS_ENABLED = os.environ.get("ENV_MANAGER_FS_ENABLED", "1") == "1"

# --- Applications ------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_cotton",
    "ninja",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# --- Database ----------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("ENV_MANAGER_DB_PATH", BASE_DIR / "db.sqlite3"),
        # Needed for select_for_update()-based optimistic-lock transactions
        # (DATA_MODEL.md "Points d'attention") not to hit "database is locked".
        "OPTIONS": {"timeout": 20},
    }
}

AUTH_USER_MODEL = "core.User"

AUTH_PASSWORD_VALIDATORS = []  # passwordless (WebAuthn) — no local password auth

# --- i18n ----------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# --- Static files --------------------------------------------------------

# Absolute (script-prefix-aware) so generated <link>/<script> URLs stay under
# the same external path when FORCE_SCRIPT_NAME is set (see above) — a plain
# relative "static/" would resolve wrong on any non-root page.
STATIC_URL = f"{FORCE_SCRIPT_NAME or ''}/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Served directly by the app (WhiteNoise) so a single container is enough in
# production — no separate web server/CDN required for static assets.
# The manifest-hashed storage requires `collectstatic` to have been run (it
# reads staticfiles.json for the hashed filenames); that's fine in prod
# builds but not in local dev/tests, so fall back to plain, unhashed static
# file storage by default.
#
# This is deliberately its OWN setting, not just `not DEBUG`: `docker build`
# runs `collectstatic` with none of docker-compose's runtime env vars set
# (those only exist at `docker run`), so DJANGO_DEBUG would be unset/"1"
# there too — tying storage choice directly to DEBUG meant collectstatic
# ran with the plain backend at build time (writing no manifest), while the
# container then started with DJANGO_DEBUG=0 at runtime expecting one,
# and 500'd on every {% static %} tag. The Dockerfile sets
# DJANGO_STATIC_MANIFEST=1 before its collectstatic step for exactly this
# reason — using it instead of DEBUG here also avoids flipping DEBUG (and
# its FERNET_KEY-generation side effect below) just to pick a storage class.
_use_manifest_static = os.environ.get("DJANGO_STATIC_MANIFEST", "0") == "1" or not DEBUG
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
            if _use_manifest_static
            else "django.contrib.staticfiles.storage.StaticFilesStorage"
        )
    },
}

# Models declare id = UUIDField(primary_key=True) explicitly (DATA_MODEL.md);
# UUIDField cannot be used as DEFAULT_AUTO_FIELD, so no default here.
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Sessions / cookies ----------------------------------------------------

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_ENGINE = "django.contrib.sessions.backends.db"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

# This app holds plaintext secrets in-session-adjacent pages (unmasked reveal,
# forms) — auto-logout an idle user after 10 minutes rather than the framework
# default of two weeks. SESSION_SAVE_EVERY_REQUEST makes this a rolling/idle
# timeout (each request resets the clock) rather than a fixed one, and it's
# enforced server-side (Django rejects an expired session key on the next
# request) — the matching client-side idle timer in app.html is just the UX
# half, forcing an immediate redirect instead of waiting for the next click.
SESSION_COOKIE_AGE = 600
SESSION_SAVE_EVERY_REQUEST = True

# Trust the scheme reported by a reverse proxy (nginx/Caddy/Traefik terminating
# TLS in front of the container) so Django knows the request is HTTPS.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Required by Django's CSRF protection for POSTs when served behind a reverse
# proxy / on a domain different from the container's own view of itself.
# Comma-separated full origins, e.g. "https://tools.example.com".
CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", os.environ.get("WEBAUTHN_ORIGIN", "")).split(",") if o
]

# --- WebAuthn (py_webauthn) --------------------------------------------------
# RP_ID must be the domain the app is served from (no scheme/port).
WEBAUTHN_RP_ID = os.environ.get("WEBAUTHN_RP_ID", "localhost")
WEBAUTHN_RP_NAME = os.environ.get("WEBAUTHN_RP_NAME", "Env Manager")
WEBAUTHN_ORIGIN = os.environ.get("WEBAUTHN_ORIGIN", "http://localhost:8000")

# --- CI/CD API token (lock/unlock only, API_CONTRACT.md "Intégration CI/CD") --
# Comma-separated list of accepted bearer tokens. One admin-managed secret per
# pipeline; scope is restricted in code to lock/unlock only, never session routes.
CI_API_TOKENS = [t for t in os.environ.get("CI_API_TOKENS", "").split(",") if t]

# Named URL (not a literal path) so it's resolved through reverse() and comes
# back script-prefixed too — same mechanism Django admin's own login redirect
# already uses, kept consistent here.
LOGIN_URL = "core:login"

# --- Logging -----------------------------------------------------------------
# Everything goes to stdout/stderr (never a file inside the container) so
# `docker logs` / your log collector picks it up. Level is configurable per
# deployment: INFO by default (variable CRUD, permission denials, imports),
# DEBUG for verbose troubleshooting, WARNING/ERROR to quiet it down.
LOG_LEVEL = os.environ.get("DJANGO_LOG_LEVEL", "INFO").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "default"},
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        # Django's own request logger already prints tracebacks for 500s;
        # keep it, but don't double-propagate to root.
        "django": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        # This app's own loggers (core.services, core.envfile, core.api, core.views).
        "core": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False},
    },
}

