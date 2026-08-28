
import pytest

from core.models import AllowedRoot, Environment, Permission, Project, User


@pytest.fixture
def tmp_root(settings, tmp_path):
    settings.ENV_MANAGER_FS_ENABLED = True
    return tmp_path


@pytest.fixture
def admin_user(db):
    u = User.objects.create(username="admin@x.com", email="admin@x.com", display_name="Admin", role=User.Role.ADMIN)
    u.set_unusable_password()
    u.save()
    return u


@pytest.fixture
def dev_user(db):
    u = User.objects.create(username="dev@x.com", email="dev@x.com", display_name="Dev", role=User.Role.DEVELOPER)
    u.set_unusable_password()
    u.save()
    return u


@pytest.fixture
def other_dev(db):
    u = User.objects.create(username="other@x.com", email="other@x.com", display_name="Other", role=User.Role.DEVELOPER)
    u.set_unusable_password()
    u.save()
    return u


@pytest.fixture
def environment(db, admin_user, tmp_root):
    root = AllowedRoot.objects.create(path=str(tmp_root), label="test-root", created_by=admin_user)
    project = Project.objects.create(name="Proj", allowed_root=root)
    env = Environment.objects.create(project=project, name="DEV", relative_path=".env")
    return env


@pytest.fixture
def dev_read_write(db, dev_user, environment):
    Permission.objects.create(user=dev_user, environment=environment, can_read=True, can_write=True, can_delete=True)
    return dev_user
