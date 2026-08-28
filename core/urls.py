from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("logout/", views.logout_view, name="logout"),
    path("", views.dashboard_view, name="dashboard"),
    path("environments/<uuid:environment_id>/", views.environment_view, name="environment"),
    path("environments/<uuid:environment_id>/variables/new/", views.variable_create_view, name="variable_create"),
    path("environments/<uuid:environment_id>/refresh/", views.environment_refresh_view, name="environment_refresh"),
    path("environments/<uuid:environment_id>/variables/<str:key>/edit/", views.variable_edit_view, name="variable_edit"),
    path("environments/<uuid:environment_id>/variables/<str:key>/delete/", views.variable_delete_view, name="variable_delete"),
    path("environments/<uuid:environment_id>/variables/<str:key>/reveal/", views.variable_reveal_view, name="variable_reveal"),
    path("environments/<uuid:environment_id>/variables/<str:key>/move/<str:direction>/", views.variable_move_view, name="variable_move"),
    path("environments/<uuid:environment_id>/groups/<str:group_name>/rename/", views.group_rename_view, name="group_rename"),
    path("environments/<uuid:environment_id>/groups/<str:group_name>/ungroup/", views.group_ungroup_view, name="group_ungroup"),
    path("environments/<uuid:environment_id>/revisions/", views.revisions_view, name="revisions"),
    path("environments/<uuid:environment_id>/revisions/<int:rev_number>/restore/", views.revision_restore_view, name="revision_restore"),
]
