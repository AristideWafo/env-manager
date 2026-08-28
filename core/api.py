"""
Django Ninja API — implements API_CONTRACT.md exactly (paths, payloads, error
codes). Mounted at /api/v1 by config/urls.py.
"""

from __future__ import annotations

import logging
import uuid
from typing import Literal, Optional

from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import NinjaAPI, Router, Schema
from ninja.security import HttpBearer, django_auth

from . import services, webauthn_service
from .models import (
    AllowedRoot,
    AuditLog,
    Credential,
    Environment,
    Permission,
    Project,
    Revision,
    User,
)
from .services import ApiError

logger = logging.getLogger(__name__)

# --- Envelope & error handling ----------------------------------------------


def envelope(data):
    return {"data": data, "meta": {"requestId": str(uuid.uuid4()), "timestamp": timezone.now().isoformat()}}


api = NinjaAPI(title="Env Manager API", version="1.0.0", urls_namespace="api")


@api.exception_handler(ApiError)
def handle_api_error(request, exc: ApiError):
    level = logging.ERROR if exc.status >= 500 else logging.WARNING
    logger.log(level, "API error %s %s: [%s] %s", request.method, request.path, exc.code, exc.message)
    return api.create_response(
        request,
        {"error": {"code": exc.code, "message": exc.message},
         "meta": {"requestId": str(uuid.uuid4()), "timestamp": timezone.now().isoformat()}},
        status=exc.status,
    )


@api.exception_handler(Exception)
def handle_unexpected(request, exc: Exception):
    logger.exception("unhandled exception in %s %s", request.method, request.path)
    return api.create_response(
        request,
        {"error": {"code": "INTERNAL_ERROR", "message": "internal error"},
         "meta": {"requestId": str(uuid.uuid4()), "timestamp": timezone.now().isoformat()}},
        status=500,
    )


# --- CI/CD bearer auth (scope: lock/unlock only) -----------------------------


class CiTokenAuth(HttpBearer):
    def authenticate(self, request, token):
        from django.conf import settings
        if token in settings.CI_API_TOKENS:
            return token
        return None


ci_auth = CiTokenAuth()


def require_admin(request: HttpRequest) -> User:
    user = request.user
    if not user.is_authenticated:
        raise ApiError("UNAUTHORIZED", 401, "authentication required")
    if not user.is_admin:
        raise ApiError("FORBIDDEN", 403, "admin role required")
    return user


# ============================= AUTH ==========================================

auth_router = Router(tags=["auth"])


class RegOptionsIn(Schema):
    invitation_token: str


class RegVerifyIn(Schema):
    invitation_token: str
    challenge: str
    device_label: str = ""
    credential: dict


class LoginOptionsIn(Schema):
    email: str


class LoginVerifyIn(Schema):
    email: str
    challenge: str
    credential: dict


@auth_router.post("/webauthn/register/options")
def register_options(request, payload: RegOptionsIn):
    try:
        user = webauthn_service.resolve_invitation_token(payload.invitation_token)
    except ValueError as e:
        raise ApiError("VALIDATION_ERROR", 422, str(e))
    return envelope(webauthn_service.registration_options(user))


@auth_router.post("/webauthn/register/verify")
def register_verify(request, payload: RegVerifyIn):
    try:
        user = webauthn_service.resolve_invitation_token(payload.invitation_token)
    except ValueError as e:
        raise ApiError("VALIDATION_ERROR", 422, str(e))
    try:
        webauthn_service.verify_registration(
            user=user, credential_json=payload.credential,
            expected_challenge_b64=payload.challenge, device_label=payload.device_label,
        )
    except Exception as e:
        services.audit(user=user, action=AuditLog.Action.LOGIN, target="register",
                        result=AuditLog.Result.FAILURE, detail=str(e))
        raise ApiError("VALIDATION_ERROR", 422, f"registration failed: {e}")
    services.audit(user=user, action=AuditLog.Action.CREATE,
                    target=f"credential:{payload.device_label or 'device'}")
    return envelope({"registered": True})


@auth_router.post("/webauthn/login/options")
def login_options_view(request, payload: LoginOptionsIn):
    user = User.objects.filter(email=payload.email, is_active=True).first()
    if not user:
        raise ApiError("VALIDATION_ERROR", 422, "unknown user")
    return envelope(webauthn_service.login_options(user))


@auth_router.post("/webauthn/login/verify")
def login_verify(request, payload: LoginVerifyIn):
    user = User.objects.filter(email=payload.email, is_active=True).first()
    if not user:
        raise ApiError("VALIDATION_ERROR", 422, "unknown user")
    try:
        webauthn_service.verify_login(
            user=user, credential_json=payload.credential, expected_challenge_b64=payload.challenge,
        )
    except Exception as e:
        services.audit(user=user, action=AuditLog.Action.LOGIN, target=user.email,
                        result=AuditLog.Result.FAILURE, detail=str(e))
        raise ApiError("VALIDATION_ERROR", 422, f"login failed: {e}")
    django_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    services.audit(user=user, action=AuditLog.Action.LOGIN, target=user.email)
    return envelope({"authenticated": True, "role": user.role})


@auth_router.post("/logout", auth=django_auth)
def logout(request):
    django_logout(request)
    return envelope({"loggedOut": True})


# ============================= USERS (ADMIN) =================================

users_router = Router(tags=["users"], auth=django_auth)


class CreateUserIn(Schema):
    email: str
    display_name: str
    role: Literal["ADMIN", "DEVELOPER"] = "DEVELOPER"


class PatchUserIn(Schema):
    is_active: Optional[bool] = None
    role: Optional[Literal["ADMIN", "DEVELOPER"]] = None


@users_router.post("/users")
def create_user(request, payload: CreateUserIn):
    admin = require_admin(request)
    if User.objects.filter(email=payload.email).exists():
        raise ApiError("VALIDATION_ERROR", 422, "email already registered")
    user = User.objects.create(
        username=payload.email, email=payload.email, display_name=payload.display_name,
        role=payload.role, is_active=True,
    )
    user.set_unusable_password()
    user.save()
    token = webauthn_service.make_invitation_token(user)
    services.audit(user=admin, action=AuditLog.Action.CREATE, target=user.email)
    # V1 has no outbound email transport wired; the invitation token is
    # returned to the admin to hand to the developer out-of-band.
    return envelope({"id": str(user.id), "email": user.email, "invitation_token": token})


@users_router.get("/users")
def list_users(request):
    require_admin(request)
    return envelope([
        {"id": str(u.id), "email": u.email, "display_name": u.display_name,
         "role": u.role, "is_active": u.is_active}
        for u in User.objects.all().order_by("email")
    ])


@users_router.patch("/users/{user_id}")
def patch_user(request, user_id: uuid.UUID, payload: PatchUserIn):
    admin = require_admin(request)
    user = get_object_or_404(User, id=user_id)
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.role is not None:
        user.role = payload.role
    user.save()
    services.audit(user=admin, action=AuditLog.Action.UPDATE, target=user.email)
    return envelope({"id": str(user.id), "is_active": user.is_active, "role": user.role})


@users_router.post("/users/{user_id}/credentials")
def add_credential_invitation(request, user_id: uuid.UUID):
    admin = require_admin(request)
    user = get_object_or_404(User, id=user_id, is_active=True)
    token = webauthn_service.make_invitation_token(user)
    services.audit(user=admin, action=AuditLog.Action.CREATE, target=f"credential-invite:{user.email}")
    return envelope({"invitation_token": token})


@users_router.delete("/users/{user_id}/credentials/{credential_id}")
def revoke_credential(request, user_id: uuid.UUID, credential_id: uuid.UUID):
    admin = require_admin(request)
    cred = get_object_or_404(Credential, id=credential_id, user_id=user_id)
    cred.status = Credential.Status.REVOKED
    cred.save(update_fields=["status"])
    services.audit(user=admin, action=AuditLog.Action.DELETE, target=f"credential:{cred.device_label or cred.id}")
    return envelope({"revoked": True})


# ============================= ALLOWED ROOTS / PROJECTS / ENVIRONMENTS ======

roots_router = Router(tags=["allowed-roots"], auth=django_auth)


class CreateRootIn(Schema):
    path: str
    label: str


@roots_router.post("/allowed-roots")
def create_root(request, payload: CreateRootIn):
    admin = require_admin(request)
    root = AllowedRoot.objects.create(path=payload.path, label=payload.label, created_by=admin)
    services.audit(user=admin, action=AuditLog.Action.CREATE, target=root.label)
    return envelope({"id": str(root.id), "path": root.path, "label": root.label})


@roots_router.get("/allowed-roots")
def list_roots(request):
    require_admin(request)
    return envelope([{"id": str(r.id), "path": r.path, "label": r.label} for r in AllowedRoot.objects.all()])


projects_router = Router(tags=["projects"], auth=django_auth)


class CreateProjectIn(Schema):
    name: str
    allowed_root_id: uuid.UUID


@projects_router.post("/projects")
def create_project(request, payload: CreateProjectIn):
    admin = require_admin(request)
    root = get_object_or_404(AllowedRoot, id=payload.allowed_root_id)
    if Project.objects.filter(name=payload.name).exists():
        raise ApiError("VALIDATION_ERROR", 422, "project name already exists")
    project = Project.objects.create(name=payload.name, allowed_root=root)
    services.audit(user=admin, action=AuditLog.Action.CREATE, target=project.name, project=project)
    return envelope({"id": str(project.id), "name": project.name})


@projects_router.get("/projects")
def list_projects(request):
    user = request.user
    if user.is_admin:
        qs = Project.objects.all()
    else:
        qs = Project.objects.filter(environments__permissions__user=user).distinct()
    return envelope([{"id": str(p.id), "name": p.name} for p in qs])


class CreateEnvironmentIn(Schema):
    name: str
    relative_path: str


@projects_router.post("/projects/{project_id}/environments")
def create_environment(request, project_id: uuid.UUID, payload: CreateEnvironmentIn):
    admin = require_admin(request)
    project = get_object_or_404(Project, id=project_id)
    if Environment.objects.filter(project=project, name=payload.name).exists():
        raise ApiError("VALIDATION_ERROR", 422, "environment name already exists for this project")
    env = Environment.objects.create(project=project, name=payload.name, relative_path=payload.relative_path)
    services.audit(user=admin, action=AuditLog.Action.CREATE, target=f"{project.name}/{env.name}",
                    project=project, environment=env)
    return envelope({"id": str(env.id), "name": env.name, "relative_path": env.relative_path, "revision": env.revision})


@projects_router.get("/projects/{project_id}/environments")
def list_environments(request, project_id: uuid.UUID):
    project = get_object_or_404(Project, id=project_id)
    qs = services.visible_environments(request.user, Environment.objects.filter(project=project))
    return envelope([
        {"id": str(e.id), "name": e.name, "revision": e.revision, "locked_for_deploy": e.locked_for_deploy}
        for e in qs
    ])


# ============================= PERMISSIONS ===================================

permissions_router = Router(tags=["permissions"], auth=django_auth)


class GrantPermissionIn(Schema):
    user_id: uuid.UUID
    can_read: bool = False
    can_write: bool = False
    can_delete: bool = False


@permissions_router.post("/environments/{environment_id}/permissions")
def grant_permission(request, environment_id: uuid.UUID, payload: GrantPermissionIn):
    admin = require_admin(request)
    environment = get_object_or_404(Environment, id=environment_id)
    target_user = get_object_or_404(User, id=payload.user_id)
    perm, _ = Permission.objects.update_or_create(
        user=target_user, environment=environment,
        defaults={"can_read": payload.can_read, "can_write": payload.can_write, "can_delete": payload.can_delete},
    )
    services.audit(user=admin, action=AuditLog.Action.UPDATE, target=f"permission:{target_user.email}",
                    project=environment.project, environment=environment)
    return envelope({"id": str(perm.id), "user_id": str(target_user.id),
                      "can_read": perm.can_read, "can_write": perm.can_write, "can_delete": perm.can_delete})


@permissions_router.get("/environments/{environment_id}/permissions")
def list_permissions(request, environment_id: uuid.UUID):
    require_admin(request)
    environment = get_object_or_404(Environment, id=environment_id)
    return envelope([
        {"user_id": str(p.user_id), "email": p.user.email, "can_read": p.can_read,
         "can_write": p.can_write, "can_delete": p.can_delete}
        for p in environment.permissions.select_related("user")
    ])


@permissions_router.delete("/environments/{environment_id}/permissions/{user_id}")
def revoke_permission(request, environment_id: uuid.UUID, user_id: uuid.UUID):
    admin = require_admin(request)
    environment = get_object_or_404(Environment, id=environment_id)
    Permission.objects.filter(environment=environment, user_id=user_id).delete()
    services.audit(user=admin, action=AuditLog.Action.DELETE, target=f"permission:{user_id}",
                    project=environment.project, environment=environment)
    return envelope({"revoked": True})


# ============================= VARIABLES =====================================

variables_router = Router(tags=["variables"], auth=django_auth)


def _get_environment_checked(request, environment_id, need: str) -> Environment:
    environment = get_object_or_404(Environment, id=environment_id)
    services.check_permission(request.user, environment, need)
    return environment


class CreateVariableIn(Schema):
    key: str
    value: str = ""
    is_secret: bool = False


class UpdateVariableIn(Schema):
    value: str
    revision: int
    is_secret: Optional[bool] = None  # UC-19: omit to keep current flag, set to flip it


class DeleteVariableIn(Schema):
    revision: int


class BatchOpIn(Schema):
    op: Literal["create", "update", "delete"]
    key: str
    value: Optional[str] = None
    is_secret: Optional[bool] = None


class BatchIn(Schema):
    revision: int
    operations: list[BatchOpIn]


@variables_router.get("/environments/{environment_id}/variables")
def list_variables(request, environment_id: uuid.UUID):
    environment = _get_environment_checked(request, environment_id, "read")
    return envelope({
        "revision": environment.revision,
        "variables": [services.serialize_variable(v) for v in environment.variables.all().order_by("key")],
    })


@variables_router.post("/environments/{environment_id}/variables")
def create_variable(request, environment_id: uuid.UUID, payload: CreateVariableIn):
    environment = _get_environment_checked(request, environment_id, "write")
    var = services.create_variable(
        environment_id=environment.id, user=request.user,
        key=payload.key, value=payload.value, is_secret=payload.is_secret,
    )
    return envelope(services.serialize_variable(var))


@variables_router.post("/environments/{environment_id}/variables/batch")
def batch_variables(request, environment_id: uuid.UUID, payload: BatchIn):
    # NB: this static path must stay registered before the /variables/{key}
    # routes below — Django resolves patterns in registration order, and
    # {key} would otherwise swallow "batch" as a key and 405 on POST.
    # Batch may mix creates/updates/deletes; require write, and additionally
    # delete permission if any delete op is present (UC-17 requires DELETE).
    environment = _get_environment_checked(request, environment_id, "write")
    if any(op.op == "delete" for op in payload.operations):
        services.check_permission(request.user, environment, "delete")
    environment = services.apply_batch(
        environment_id=environment.id, user=request.user, revision=payload.revision,
        operations=[op.dict() for op in payload.operations],
    )
    return envelope({
        "revision": environment.revision,
        "variables": [services.serialize_variable(v) for v in environment.variables.all().order_by("key")],
    })


class ReorderVariablesIn(Schema):
    keys: list[str]


@variables_router.post("/environments/{environment_id}/variables/reorder")
def reorder_variables(request, environment_id: uuid.UUID, payload: ReorderVariablesIn):
    # NB: must stay registered before /variables/{key} routes below — same
    # reason as /variables/batch above (Django resolves patterns in
    # registration order; {key} would otherwise swallow "reorder").
    environment = _get_environment_checked(request, environment_id, "write")
    services.reorder_variables(environment_id=environment.id, user=request.user, ordered_keys=payload.keys)
    return envelope({
        "variables": [services.serialize_variable(v) for v in environment.variables.all().order_by("order")],
    })


class MoveVariableIn(Schema):
    direction: Literal["up", "down"]


@variables_router.post("/environments/{environment_id}/variables/{key}/move")
def move_variable(request, environment_id: uuid.UUID, key: str, payload: MoveVariableIn):
    environment = _get_environment_checked(request, environment_id, "write")
    services.swap_variable_order(environment_id=environment.id, user=request.user, key=key, direction=payload.direction)
    return envelope({
        "variables": [services.serialize_variable(v) for v in environment.variables.all().order_by("order")],
    })


class RenameGroupIn(Schema):
    old_name: str
    new_name: str


@variables_router.post("/environments/{environment_id}/groups/rename")
def rename_group(request, environment_id: uuid.UUID, payload: RenameGroupIn):
    environment = _get_environment_checked(request, environment_id, "write")
    updated = services.rename_group(
        environment_id=environment.id, user=request.user,
        old_name=payload.old_name, new_name=payload.new_name,
    )
    return envelope({"updated": updated})


class UngroupIn(Schema):
    group_name: str


@variables_router.post("/environments/{environment_id}/groups/ungroup")
def ungroup(request, environment_id: uuid.UUID, payload: UngroupIn):
    environment = _get_environment_checked(request, environment_id, "write")
    updated = services.ungroup(environment_id=environment.id, user=request.user, group_name=payload.group_name)
    return envelope({"updated": updated})


class UpdateLayoutIn(Schema):
    group: Optional[str] = None
    comment: Optional[str] = None


@variables_router.patch("/environments/{environment_id}/variables/{key}/layout")
def update_variable_layout(request, environment_id: uuid.UUID, key: str, payload: UpdateLayoutIn):
    # Display metadata only (core/envdoc.py) — no revision/lock semantics, so
    # write permission is the only check (no locked_for_deploy gate).
    environment = _get_environment_checked(request, environment_id, "write")
    var = services.update_variable_layout(
        environment_id=environment.id, user=request.user, key=key,
        group_name=payload.group, leading_comment=payload.comment,
    )
    return envelope(services.serialize_variable(var))


@variables_router.patch("/environments/{environment_id}/variables/{key}")
def update_variable(request, environment_id: uuid.UUID, key: str, payload: UpdateVariableIn):
    environment = _get_environment_checked(request, environment_id, "write")
    var = services.update_variable(
        environment_id=environment.id, user=request.user, key=key,
        value=payload.value, revision=payload.revision, is_secret=payload.is_secret,
    )
    return envelope(services.serialize_variable(var))


@variables_router.delete("/environments/{environment_id}/variables/{key}")
def delete_variable(request, environment_id: uuid.UUID, key: str, payload: DeleteVariableIn):
    environment = _get_environment_checked(request, environment_id, "delete")
    services.delete_variable(environment_id=environment.id, user=request.user, key=key, revision=payload.revision)
    return envelope({"deleted": key})


class RevealIn(Schema):
    confirm: bool = False


@variables_router.post("/environments/{environment_id}/variables/{key}/reveal")
def reveal_variable(request, environment_id: uuid.UUID, key: str, payload: RevealIn):
    environment = _get_environment_checked(request, environment_id, "read")
    if not payload.confirm:
        raise ApiError("VALIDATION_ERROR", 422, "explicit confirm required to reveal a secret")
    value = services.reveal_variable(environment=environment, user=request.user, key=key)
    return envelope({"key": key, "value": value})


# ============================= REVISIONS =====================================

revisions_router = Router(tags=["revisions"], auth=django_auth)


@revisions_router.get("/environments/{environment_id}/revisions")
def list_revisions(request, environment_id: uuid.UUID):
    environment = _get_environment_checked(request, environment_id, "read")
    return envelope([
        {"revision_number": r.revision_number,
         "created_by": r.created_by.email if r.created_by else None,
         "created_at": r.created_at.isoformat()}
        for r in environment.revisions.all()
    ])


@revisions_router.get("/environments/{environment_id}/revisions/{rev_number}")
def get_revision(request, environment_id: uuid.UUID, rev_number: int):
    environment = _get_environment_checked(request, environment_id, "read")
    rev = get_object_or_404(Revision, environment=environment, revision_number=rev_number)
    # Mask secret values in the snapshot the same way the live list does.
    snapshot = [
        {"key": e["key"], "value": None if e["is_secret"] else e["value"], "is_secret": e["is_secret"]}
        for e in rev.snapshot
    ]
    return envelope({"revision_number": rev.revision_number, "snapshot": snapshot, "created_at": rev.created_at.isoformat()})


@revisions_router.post("/environments/{environment_id}/revisions/{rev_number}/restore")
def restore_revision(request, environment_id: uuid.UUID, rev_number: int):
    environment = _get_environment_checked(request, environment_id, "write")
    environment = services.restore_revision(environment_id=environment.id, user=request.user, revision_number=rev_number)
    return envelope({"revision": environment.revision})


# ============================= AUDIT (ADMIN) =================================

audit_router = Router(tags=["audit"], auth=django_auth)


@audit_router.get("/audit")
def list_audit(request, project_id: Optional[uuid.UUID] = None, environment_id: Optional[uuid.UUID] = None):
    require_admin(request)
    qs = AuditLog.objects.all()
    if project_id:
        qs = qs.filter(project_id=project_id)
    if environment_id:
        qs = qs.filter(environment_id=environment_id)
    # "from"/"to" is a reserved word in Python params; read straight off GET.
    from_ = request.GET.get("from")
    to = request.GET.get("to")
    if from_:
        qs = qs.filter(created_at__gte=from_)
    if to:
        qs = qs.filter(created_at__lte=to)
    return envelope([
        {"id": str(a.id), "user": a.user.email if a.user else None, "action": a.action,
         "target": a.target, "result": a.result, "detail": a.detail, "created_at": a.created_at.isoformat()}
        for a in qs[:500]
    ])


# ============================= CI/CD LOCK ====================================

ci_router = Router(tags=["ci"], auth=ci_auth)


@ci_router.post("/environments/{environment_id}/lock")
def lock_environment(request, environment_id: uuid.UUID):
    environment = get_object_or_404(Environment, id=environment_id)
    environment = services.set_lock(environment_id=environment.id, locked=True, actor_label="ci-token")
    return envelope({"locked_for_deploy": environment.locked_for_deploy})


@ci_router.post("/environments/{environment_id}/unlock")
def unlock_environment(request, environment_id: uuid.UUID):
    environment = get_object_or_404(Environment, id=environment_id)
    environment = services.set_lock(environment_id=environment.id, locked=False, actor_label="ci-token")
    return envelope({"locked_for_deploy": environment.locked_for_deploy})


# --- Mount ---------------------------------------------------------------

api.add_router("/auth", auth_router)
api.add_router("", users_router)
api.add_router("", roots_router)
api.add_router("", projects_router)
api.add_router("", permissions_router)
api.add_router("", variables_router)
api.add_router("", revisions_router)
api.add_router("", audit_router)
api.add_router("", ci_router)
