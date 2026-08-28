# Env Manager

[![CI](https://github.com/AristideWafo/env-manager/actions/workflows/ci.yml/badge.svg?branch=prod)](https://github.com/AristideWafo/env-manager/actions/workflows/ci.yml)
[![Release](https://github.com/AristideWafo/env-manager/actions/workflows/release.yml/badge.svg)](https://github.com/AristideWafo/env-manager/actions/workflows/release.yml)
[![Latest Release](https://img.shields.io/github/v/release/AristideWafo/env-manager?sort=semver)](https://github.com/AristideWafo/env-manager/releases)
[![License: MIT](https://img.shields.io/github/license/AristideWafo/env-manager)](LICENSE)

Self-hosted web app for teams to manage `.env` variables across projects
without server access. WebAuthn (passkey) login, per-environment
permissions, optimistic-lock revisions, full audit trail, and atomic `.env`
writes. Spec lives in [`AGENT_CONTEXT.md`](AGENT_CONTEXT.md),
[`DATA_MODEL.md`](DATA_MODEL.md), [`USE_CASES.md`](USE_CASES.md) and
[`API_CONTRACT.md`](API_CONTRACT.md) at the repo root — read those first for
the "why", this file only covers the "how to run it". See
[`CHANGELOG.md`](CHANGELOG.md) for release history.

## Stack

Python 3.12 · Django 5.2 + Django Ninja · `webauthn` (py_webauthn) ·
SQLite · `cryptography` (Fernet) · Django templates + HTMX + Tailwind (CDN).

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # then edit at least ENV_MANAGER_FERNET_KEY for prod-like runs
python manage.py migrate
python manage.py createsuperuser   # ops/break-glass access to /admin/, separate from passkey login
python manage.py runserver
```

In `DEBUG=1` (the default), a fixed dev Fernet key is used automatically so
you don't need to set `ENV_MANAGER_FERNET_KEY` locally — never rely on that
key outside development.

Run tests / lint:

```bash
pytest
ruff check .
```

## First-run walkthrough

1. `createsuperuser`, log into `/admin/` with that account.
2. In `/admin/`, add a `Core > User` with role `ADMIN` (this is your app-level
   admin — separate from Django's `is_staff`/`is_superuser`).
3. Select that user in the admin changelist → action **"Generate passkey
   invitation link"** → open the printed `/register/?token=...` URL in a
   browser that supports WebAuthn (needs HTTPS or `localhost`) and register a
   device.
4. Log in at `/login/` with that email using the passkey.
5. As ADMIN, create an `AllowedRoot` (a real absolute path on the host,
   e.g. `/opt/projects`), a `Project` under it, and an `Environment` (e.g.
   `DEV`, relative path `.env`) — all via `/admin/`.
6. Grant a `Permission` (read/write/delete) to a `DEVELOPER` user on that
   environment, then invite them the same way as step 3.
7. The developer manages variables at `/environments/<id>/`.

## CI/CD integration

The pipeline calls `POST /api/v1/environments/{id}/lock` before deploying and
`POST /api/v1/environments/{id}/unlock` after, using a bearer token from
`CI_API_TOKENS` (comma-separated, admin-managed, stored as a pipeline
secret) — see `API_CONTRACT.md`. The pipeline then reads the `.env` file
directly off disk; Env Manager never triggers a deploy itself.

## Deploy (production, no repo checkout needed)

Pull the published image and run it with `docker run`, no need to clone this
repo or build anything locally:

```bash
docker run -d \
  --name env-manager \
  --restart unless-stopped \
  -p 8000:8000 \
  -v env-manager-data:/app/data \
  -v /opt/projects:/data/projects \
  -e DJANGO_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')" \
  -e ENV_MANAGER_FERNET_KEY="$(python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" \
  -e DJANGO_ALLOWED_HOSTS=env.example.com \
  -e WEBAUTHN_RP_ID=env.example.com \
  -e WEBAUTHN_ORIGIN=https://env.example.com \
  ghcr.io/aristidewafo/env-manager:latest
```

Replace `/opt/projects` with the host directory this instance should be
allowed to write `.env` files into, and the hostname values with your real
domain (WebAuthn requires HTTPS or `localhost`). Store the generated
`DJANGO_SECRET_KEY` / `ENV_MANAGER_FERNET_KEY` somewhere safe — losing the
Fernet key makes every stored secret unrecoverable. Put the app behind a
reverse proxy (nginx, Caddy, Traefik) that terminates TLS.

Prefer Compose? Set `ENV_MANAGER_IMAGE=ghcr.io/aristidewafo/env-manager:latest`
in your `.env` file and remove the `build: .` line from `docker-compose.yml`
to skip building locally — see the [Docker](#docker) section below for the
full variable reference.

Any tagged release also works instead of `:latest`, e.g.
`ghcr.io/aristidewafo/env-manager:0.1.0` — see [Releases](https://github.com/AristideWafo/env-manager/releases).

## Docker

```bash
cp .env.example .env   # fill in DJANGO_SECRET_KEY, ENV_MANAGER_FERNET_KEY, etc.
docker compose --env-file .env up --build
```

The SQLite file persists in the `db-data` volume; `PROJECTS_ROOT` is bind-mounted
so the container can write `.env` files where your existing CI/CD pipeline
expects them — it must match the `AllowedRoot.path` rows declared in-app.

## Security notes

- Secrets are Fernet-encrypted at rest (`Variable.encrypted_value`); the key
  lives outside SQLite (env var / secret store), never in the repo or DB.
- Every filesystem write is tmp-file → fsync → atomic rename, and every path
  is re-validated against `AllowedRoot` right before writing.
- Every mutating action is permission-checked server-side, revision-bumped,
  and audit-logged; secret values are never written to logs or audit rows.
