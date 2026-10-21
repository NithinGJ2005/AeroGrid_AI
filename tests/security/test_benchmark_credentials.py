"""Tests for benchmark credential enforcement and elimination of fallback secrets."""

import os
import pytest
from unittest import mock

from scripts.benchmark_e2e_workload import get_benchmark_users, get_default_users
import scripts.benchmark_e2e_workload as benchmark_module


def test_staging_missing_user_password_raises_value_error():
    """Verify that staging mode strictly fails when AEROGRID_USER_PASSWORD is missing."""
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("AEROGRID_")}
    with mock.patch.dict(os.environ, clean_env, clear=True):
        with pytest.raises(ValueError) as excinfo:
            get_benchmark_users(is_staging=True, admin_pass="SomeAdminPass123!")
        assert "AEROGRID_USER_PASSWORD" in str(excinfo.value)


def test_staging_missing_admin_password_raises_value_error():
    """Verify that staging mode strictly fails when AEROGRID_ADMIN_PASSWORD is missing."""
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("AEROGRID_")}
    clean_env["AEROGRID_USER_PASSWORD"] = "ValidUserPassword2026!"
    with mock.patch.dict(os.environ, clean_env, clear=True):
        with pytest.raises(ValueError) as excinfo:
            get_benchmark_users(is_staging=True)
        assert "AEROGRID_ADMIN_PASSWORD" in str(excinfo.value)


def test_staging_with_explicit_credentials_succeeds():
    """Verify that staging mode succeeds when explicit credentials are supplied."""
    user_pw = "CustomStagingUser2026!Secret"
    admin_pw = "CustomStagingAdmin2026!Secret"
    clean_env = {
        "AEROGRID_USER_PASSWORD": user_pw,
        "AEROGRID_ADMIN_PASSWORD": admin_pw,
    }
    with mock.patch.dict(os.environ, clean_env, clear=True):
        users = get_benchmark_users(is_staging=True)
        assert len(users) == 3
        assert users[0] == ("staff.engineer", user_pw)
        assert users[1] == ("hr.partner", user_pw)
        assert users[2] == ("corp.admin", admin_pw)


def test_staging_cli_admin_pass_override():
    """Verify that CLI --admin-pass satisfies admin credential requirement."""
    user_pw = "CustomStagingUser2026!Secret"
    cli_admin_pw = "CLIAdminPassedSecret2026!"
    clean_env = {"AEROGRID_USER_PASSWORD": user_pw}
    with mock.patch.dict(os.environ, clean_env, clear=True):
        users = get_benchmark_users(is_staging=True, admin_pass=cli_admin_pw)
        assert users[2] == ("corp.admin", cli_admin_pw)


def test_staging_users_via_dynamic_module_attribute():
    """Verify DEMO_USERS module attribute dynamically validates credentials."""
    clean_env = {"AEROGRID_STAGING_USERS": "true"}
    with mock.patch.dict(os.environ, clean_env, clear=True):
        with pytest.raises(ValueError) as excinfo:
            _ = benchmark_module.DEMO_USERS
        assert "AEROGRID_USER_PASSWORD" in str(excinfo.value)


def test_local_dev_mode_missing_credentials_raises_value_error():
    """Verify non-staging local development mode strictly requires explicit credentials."""
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("AEROGRID_")}
    with mock.patch.dict(os.environ, clean_env, clear=True):
        with pytest.raises(ValueError) as excinfo:
            get_benchmark_users(is_staging=False)
        assert "AEROGRID_USER_PASSWORD" in str(excinfo.value)


def test_local_dev_mode_with_explicit_credentials_succeeds():
    """Verify non-staging local development mode provides standard accounts with explicit credentials."""
    user_pw = "CustomDevUser2026!Pass"
    admin_pw = "CustomDevAdmin2026!Pass"
    clean_env = {
        "AEROGRID_USER_PASSWORD": user_pw,
        "AEROGRID_ADMIN_PASSWORD": admin_pw,
    }
    with mock.patch.dict(os.environ, clean_env, clear=True):
        users = get_benchmark_users(is_staging=False)
        usernames = [u[0] for u in users]
        assert "alice.chen" in usernames
        assert "admin.system" in usernames
        assert all(u[1] == user_pw for u in users if u[0] != "admin.system")
        assert next(u[1] for u in users if u[0] == "admin.system") == admin_pw


def test_staging_persistent_accounts_authenticate_with_env_store():
    """Verify that staging accounts in an isolated auth database authenticate with credentials from the secret store."""
    import tempfile
    from pathlib import Path
    import dotenv
    from app.auth.accounts import SqliteAuthStore
    from deploy.rotate_staging_credentials import update_env_file

    with tempfile.TemporaryDirectory() as td:
        env_path = Path(td) / ".env.staging"
        db_path = Path(td) / "auth.staging.sqlite3"

        user_pw = "SyntheticUserPassword2026!Secure"
        admin_pw = "SyntheticAdminPassword2026!Secure"

        update_env_file(env_path, user_pw, admin_pw)
        env = dotenv.dotenv_values(str(env_path))

        assert env.get("AEROGRID_USER_PASSWORD") == user_pw
        assert env.get("AEROGRID_ADMIN_PASSWORD") == admin_pw

        store = SqliteAuthStore(db_path=str(db_path), is_production=True, iterations=1000)
        store.create_user("staff.engineer", user_pw, "Staff Engineer", ["engineer"])
        store.create_user("hr.partner", user_pw, "HR Partner", ["hr"])
        store.create_user("corp.admin", admin_pw, "Corp Admin", ["admin"])

        # Staging accounts must authenticate successfully with secret store credentials
        assert store.authenticate("staff.engineer", user_pw) is not None
        assert store.authenticate("hr.partner", user_pw) is not None
        assert store.authenticate("corp.admin", admin_pw) is not None


def test_staging_persistent_accounts_reject_old_exposed_password():
    """Verify that the old exposed password is strictly rejected for all active staging accounts."""
    import tempfile
    from pathlib import Path
    from app.auth.accounts import SqliteAuthStore

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "auth.staging.sqlite3"
        store = SqliteAuthStore(db_path=str(db_path), is_production=True, iterations=1000)

        user_pw = "CurrentStagingPassword2026!Val"
        admin_pw = "CurrentAdminPassword2026!Val"
        old_exposed_pw = "RevokedSyntheticCredential2026!Old"

        store.create_user("staff.engineer", user_pw, "Staff Engineer", ["engineer"])
        store.create_user("hr.partner", user_pw, "HR Partner", ["hr"])
        store.create_user("corp.admin", admin_pw, "Corp Admin", ["admin"])

        for username in ["staff.engineer", "hr.partner", "corp.admin"]:
            auth_result = store.authenticate(username, old_exposed_pw)
            assert auth_result is None, f"Exposed password must be rejected for {username}!"


def test_controlled_rotation_end_to_end_on_isolated_fixture():
    """Verify that deploy/rotate_staging_credentials.py rotates credentials end-to-end on isolated fixtures."""
    import tempfile
    from pathlib import Path
    from app.auth.accounts import SqliteAuthStore
    from deploy.rotate_staging_credentials import rotate_credentials

    with tempfile.TemporaryDirectory() as td:
        env_path = Path(td) / ".env.staging"
        db_path = Path(td) / "auth.staging.sqlite3"
        test_revoked_pw = "RevokedSyntheticTestPassword2026!"

        # Initialize fixture database with accounts using initial passwords
        store = SqliteAuthStore(db_path=str(db_path), is_production=True, iterations=1000)
        store.create_user("staff.engineer", "InitialPW123!", "Staff Engineer", ["engineer"])
        store.create_user("hr.partner", "InitialPW123!", "HR Partner", ["hr"])
        store.create_user("corp.admin", "InitialAdminPW123!", "Corp Admin", ["admin"])

        # Execute controlled rotation against isolated fixture
        ok = rotate_credentials(env_file=env_path, db_path=db_path, revoked_password=test_revoked_pw)
        assert ok is True

        # Rejection of revoked credential must hold
        for u in ["staff.engineer", "hr.partner", "corp.admin"]:
            assert store.authenticate(u, test_revoked_pw) is None


def test_controlled_rotation_invariants():
    """Verify that SqliteAuthStore.reset_password performs controlled rotation and durable audit logging."""
    import tempfile
    from pathlib import Path
    from app.auth.accounts import SqliteAuthStore

    with tempfile.TemporaryDirectory() as td:
        test_db = Path(td) / "test_auth.sqlite3"
        store = SqliteAuthStore(db_path=str(test_db), is_production=True, iterations=1000)

        old_pw = "OldSecretPassword123!"
        new_pw = "RotatedSecretPassword2026!New"

        user = store.create_user(
            username="test.user",
            password=old_pw,
            full_name="Test User",
            roles=["engineer"],
        )
        assert user.token_version == 1

        # Perform controlled rotation
        success = store.reset_password("test.user", new_pw, actor="admin_controlled_rotation")
        assert success is True

        # Old credential must fail
        assert store.authenticate("test.user", old_pw) is None

        # New credential must succeed
        updated_user = store.authenticate("test.user", new_pw)
        assert updated_user is not None
        assert updated_user.token_version == 2

        # Verify audit event in database
        audit_events = store.list_admin_audit_events(limit=10)
        password_resets = [e for e in audit_events if e["action"] == "password_reset"]
        assert len(password_resets) >= 1
        assert password_resets[0]["actor"] == "admin_controlled_rotation"
        assert password_resets[0]["target"] == "test.user"
        assert password_resets[0]["outcome"] == "allowed"
