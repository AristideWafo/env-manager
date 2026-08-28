"""
Server-rendered HTMX UI for developer flows (login, dashboard, variable CRUD,
revision history). Admin-only management (users, allowed roots, projects,
environments, permissions) is covered by the Django admin — see core/admin.py
and AGENT_CONTEXT.md's "admin auto-généré utile en interne" decision.

These views call core.services directly (same functions the JSON API uses) so
permission checks / audit / revision logic only live in one place.
"""

import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from . import services
from .models import Environment, Project
from .services import ApiError

logger = logging.getLogger(__name__)


def _api_error_response(request, e: ApiError):
    level = logging.ERROR if e.status >= 500 else logging.WARNING
    logger.log(level, "view error %s %s: [%s] %s", request.method, request.path, e.code, e.message)
    return render(request, "_error.html", {"message": e.message}, status=e.status)


def login_view(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    return render(request, "login.html")


def register_view(request):
    token = request.GET.get("token", "")
    return render(request, "register.html", {"token": token})


@login_required
def logout_view(request):
    from django.contrib.auth import logout
    logout(request)
    return redirect("core:login")


@login_required
def dashboard_view(request):
    if request.user.is_admin:
        projects = Project.objects.prefetch_related("environments").all()
    else:
        projects = Project.objects.filter(
            environments__permissions__user=request.user
        ).distinct().prefetch_related("environments")
    all_envs = [e for p in projects for e in p.environments.all()]
    return render(request, "dashboard.html", {
        "projects": projects,
        "total_environments": len(all_envs),
        "locked_environments": sum(1 for e in all_envs if e.locked_for_deploy),
    })


def _env_or_403(request, environment_id, need):
    environment = get_object_or_404(Environment, id=environment_id)
    try:
        services.check_permission(request.user, environment, need)
    except ApiError:
        return None, HttpResponseForbidden("insufficient permission")
    return environment, None


@login_required
def environment_view(request, environment_id):
    environment, err = _env_or_403(request, environment_id, "read")
    if err:
        return err
    can_write = environment.locked_for_deploy is False and _has(request.user, environment, "write")
    can_delete = _has(request.user, environment, "delete")
    # First visit to an environment whose .env file already has content on
    # disk (e.g. it predates being declared here) — pull those keys in as
    # real, manageable variables instead of showing an empty table.
    if can_write and not environment.variables.exists():
        try:
            services.import_variables_from_file(environment_id=environment.id, user=request.user)
        except ApiError:
            pass  # best-effort; page still renders with whatever's already tracked
    variables = [services.serialize_variable(v) for v in environment.variables.all().order_by("order")]
    return render(request, "environment.html", {
        "environment": environment, "variables": variables,
        "can_write": can_write, "can_delete": can_delete,
    })


def _has(user, environment, need):
    if user.is_admin:
        return True
    perm = environment.permissions.filter(user=user).first()
    return bool(perm and getattr(perm, f"can_{need}"))


def _group_names(environment):
    """Distinct, non-empty group names currently in use, for the create/edit
    form's group suggestions (datalist) — not a separate Group table, group
    membership is just Variable.group_name (see DATA_MODEL.md)."""
    return sorted({g for g in environment.variables.values_list("group_name", flat=True) if g})


def _render_variables_fragment(request, environment):
    variables = [services.serialize_variable(v) for v in environment.variables.all().order_by("order")]
    return render(request, "_variables_table.html", {
        "environment": environment, "variables": variables,
        "can_write": _has(request.user, environment, "write") and not environment.locked_for_deploy,
        "can_delete": _has(request.user, environment, "delete") and not environment.locked_for_deploy,
    })


@login_required
def variable_create_view(request, environment_id):
    environment, err = _env_or_403(request, environment_id, "write")
    if err:
        return err
    if request.method == "POST":
        try:
            services.create_variable(
                environment_id=environment.id, user=request.user,
                key=request.POST["key"], value=request.POST.get("value", ""),
                is_secret=request.POST.get("is_secret") == "on",
                group_name=request.POST.get("group", "").strip(),
                leading_comment=request.POST.get("comment", "").strip(),
            )
        except ApiError as e:
            return _api_error_response(request, e)
        environment.refresh_from_db()
        return _render_variables_fragment(request, environment)
    return render(request, "_variable_form.html", {
        "environment": environment, "group_names": _group_names(environment),
    })


@login_required
def variable_edit_view(request, environment_id, key):
    environment, err = _env_or_403(request, environment_id, "write")
    if err:
        return err
    if request.method == "POST":
        try:
            # Layout metadata FIRST, value write SECOND: update_variable's
            # write (_bump_revision_and_write) renders the file from
            # whatever group_name/leading_comment hold *right now* — doing
            # it the other way round would write the file once with the
            # old group/comment, then never rewrite it to match (layout
            # changes don't trigger a write on their own; see
            # update_variable_layout). Always applied so clearing the
            # field in the form clears it on the variable too.
            services.update_variable_layout(
                environment_id=environment.id, user=request.user, key=key,
                group_name=request.POST.get("group", "").strip(),
                leading_comment=request.POST.get("comment", "").strip(),
            )
            services.update_variable(
                environment_id=environment.id, user=request.user, key=key,
                value=request.POST.get("value", ""), revision=int(request.POST["revision"]),
                is_secret=request.POST.get("is_secret") == "on",
            )
        except ApiError as e:
            return _api_error_response(request, e)
        environment.refresh_from_db()
        return _render_variables_fragment(request, environment)
    var = environment.variables.get(key=key)
    return render(request, "_variable_edit_form.html", {
        "environment": environment, "var": var, "group_names": _group_names(environment),
    })


@login_required
def variable_delete_view(request, environment_id, key):
    environment, err = _env_or_403(request, environment_id, "delete")
    if err:
        return err
    try:
        services.delete_variable(
            environment_id=environment.id, user=request.user, key=key,
            revision=int(request.POST["revision"]),
        )
    except ApiError as e:
        return _api_error_response(request, e)
    environment.refresh_from_db()
    return _render_variables_fragment(request, environment)


@login_required
def variable_reveal_view(request, environment_id, key):
    environment, err = _env_or_403(request, environment_id, "read")
    if err:
        return err
    if request.POST.get("confirm") != "on":
        return render(request, "_error.html", {"message": "confirmation required"}, status=422)
    value = services.reveal_variable(environment=environment, user=request.user, key=key)
    return render(request, "_revealed_value.html", {"key": key, "value": value})


@login_required
def environment_refresh_view(request, environment_id):
    """Manual 'Refresh from file': re-reads the on-disk .env and imports any
    key not already tracked in DB (additive-only — see
    services.import_variables_from_file). Unlike the auto-import on first
    visit (environment_view), this is re-triggerable any time, e.g. after
    hand-editing the file outside the app."""
    environment, err = _env_or_403(request, environment_id, "write")
    if err:
        return err
    try:
        services.import_variables_from_file(environment_id=environment.id, user=request.user)
    except ApiError as e:
        return _api_error_response(request, e)
    environment.refresh_from_db()
    return _render_variables_fragment(request, environment)


@login_required
def variable_move_view(request, environment_id, key, direction):
    environment, err = _env_or_403(request, environment_id, "write")
    if err:
        return err
    try:
        services.swap_variable_order(environment_id=environment.id, user=request.user, key=key, direction=direction)
    except ApiError as e:
        return _api_error_response(request, e)
    environment.refresh_from_db()
    return _render_variables_fragment(request, environment)


@login_required
def group_rename_view(request, environment_id, group_name):
    environment, err = _env_or_403(request, environment_id, "write")
    if err:
        return err
    # hx-prompt (see _variables_table.html) sends the entered value in the
    # HX-Prompt request header, not as a form field.
    new_name = request.POST.get("new_name") or request.headers.get("HX-Prompt", "")
    try:
        services.rename_group(environment_id=environment.id, user=request.user, old_name=group_name, new_name=new_name)
    except ApiError as e:
        return _api_error_response(request, e)
    return _render_variables_fragment(request, environment)


@login_required
def group_ungroup_view(request, environment_id, group_name):
    environment, err = _env_or_403(request, environment_id, "write")
    if err:
        return err
    try:
        services.ungroup(environment_id=environment.id, user=request.user, group_name=group_name)
    except ApiError as e:
        return _api_error_response(request, e)
    return _render_variables_fragment(request, environment)


@login_required
def revisions_view(request, environment_id):
    environment, err = _env_or_403(request, environment_id, "read")
    if err:
        return err
    return render(request, "revisions.html", {
        "environment": environment, "revisions": environment.revisions.all(),
        "can_write": _has(request.user, environment, "write"),
    })


@login_required
def revision_restore_view(request, environment_id, rev_number):
    environment, err = _env_or_403(request, environment_id, "write")
    if err:
        return err
    try:
        services.restore_revision(environment_id=environment.id, user=request.user, revision_number=rev_number)
    except ApiError as e:
        return _api_error_response(request, e)
    return redirect("core:environment", environment_id=environment.id)
