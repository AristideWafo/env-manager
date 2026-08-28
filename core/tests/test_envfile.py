import pytest

from core.envfile import PathNotAllowed, atomic_write, render_dotenv, resolve_environment_path
from core.models import AllowedRoot, Environment, Project


@pytest.mark.django_db
def test_relative_path_traversal_outside_root_is_rejected(admin_user, tmp_path):
    root = AllowedRoot.objects.create(path=str(tmp_path), label="r", created_by=admin_user)
    project = Project.objects.create(name="P", allowed_root=root)
    env = Environment.objects.create(project=project, name="DEV", relative_path="../../etc/passwd")
    with pytest.raises(PathNotAllowed):
        resolve_environment_path(env)


@pytest.mark.django_db
def test_normal_relative_path_resolves_under_root(admin_user, tmp_path):
    root = AllowedRoot.objects.create(path=str(tmp_path), label="r", created_by=admin_user)
    project = Project.objects.create(name="P", allowed_root=root)
    env = Environment.objects.create(project=project, name="DEV", relative_path="config/.env")
    resolved = resolve_environment_path(env)
    assert resolved == (tmp_path / "config" / ".env").resolve()


def test_render_dotenv_escapes_and_quotes():
    text = render_dotenv([{"key": "A", "value": 'has "quote" and \\ and\nnewline'}])
    assert text == 'A="has \\"quote\\" and \\\\ and\\nnewline"\n'


def test_atomic_write_produces_final_file_no_tmp_left(tmp_path, settings):
    settings.ENV_MANAGER_FS_ENABLED = True
    target = tmp_path / "sub" / ".env"
    atomic_write(target, "A=1\n")
    assert target.read_text() == "A=1\n"
    leftovers = list(tmp_path.rglob(".*.tmp-*"))
    assert leftovers == []
