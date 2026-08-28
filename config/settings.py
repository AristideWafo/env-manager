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

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

# Served directly by the app (WhiteNoise) so a single container is enough in
# production — no separate web server/CDN required for static assets.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
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

LOGIN_URL = "/login/"
