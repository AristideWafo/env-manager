"""
Server-rendered HTMX UI for developer flows (login, dashboard, variable CRUD,
revision history). Admin-only management (users, allowed roots, projects,
environments, permissions) is covered by the Django admin — see core/admin.py
and AGENT_CONTEXT.md's "admin auto-généré utile en interne" decision.

These views call core.services directly (same functions the JSON API uses) so
permission checks / audit / revision logic only live in one place.
"""

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from . import services
from .models import Environment, Project
from .services import ApiError


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
    variables = [services.serialize_variable(v) for v in environment.variables.all().order_by("key")]
    can_write = environment.locked_for_deploy is False and _has(request.user, environment, "write")
    can_delete = _has(request.user, environment, "delete")
    return render(request, "environment.html", {
        "environment": environment, "variables": variables,
        "can_write": can_write, "can_delete": can_delete,
    })


def _has(user, environment, need):
    if user.is_admin:
        return True
    perm = environment.permissions.filter(user=user).first()
    return bool(perm and getattr(perm, f"can_{need}"))


def _render_variables_fragment(request, environment):
    variables = [services.serialize_variable(v) for v in environment.variables.all().order_by("key")]
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
            )
        except ApiError as e:
            return render(request, "_error.html", {"message": e.message}, status=e.status)
        environment.refresh_from_db()
        return _render_variables_fragment(request, environment)
    return render(request, "_variable_form.html", {"environment": environment})


@login_required
def variable_edit_view(request, environment_id, key):
    environment, err = _env_or_403(request, environment_id, "write")
    if err:
        return err
    if request.method == "POST":
        try:
            services.update_variable(
                environment_id=environment.id, user=request.user, key=key,
                value=request.POST.get("value", ""), revision=int(request.POST["revision"]),
                is_secret=request.POST.get("is_secret") == "on",
            )
        except ApiError as e:
            return render(request, "_error.html", {"message": e.message}, status=e.status)
        environment.refresh_from_db()
        return _render_variables_fragment(request, environment)
    var = environment.variables.get(key=key)
    return render(request, "_variable_edit_form.html", {"environment": environment, "var": var})


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
        return render(request, "_error.html", {"message": e.message}, status=e.status)
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
        return render(request, "_error.html", {"message": e.message}, status=e.status)
    return redirect("core:environment", environment_id=environment.id)
