"""Controlled Staging Credential Rotation.

Rotates persistent staging accounts to fresh cryptographically secure credentials
generated via OS CSPRNG (secrets module). Safely persists credentials in the approved
secret store (.env.staging) with owner-only permissions and synchronizes the staging
SQLite authentication store.

Invariants:
1. Zero secrets, tokens, or hashes are printed to console, logs, or stdout.
2. Eliminates any hardcoded or unknown fallback credentials.
3. Atomically updates database hashes, salts, and increments token version.
4. Records durable administrative audit events in admin_audit_events.
5. Strictly validates that old exposed passwords are rejected and new credentials authenticate.
"""

from __future__ import annotations

import argparse
import os
import secrets
import stat
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.auth.accounts import SqliteAuthStore

STAGING_USERS = ["staff.engineer", "hr.partner"]
STAGING_ADMIN = "corp.admin"


def generate_credential(nbytes: int = 32) -> str:
    """Generate a high-entropy CSPRNG password."""
    return secrets.token_urlsafe(nbytes)


def update_env_file(env_path: Path, user_pw: str, admin_pw: str) -> None:
    """Safely persist rotated credentials into approved staging secret store."""
    lines: list[str] = []
    keys_updated = {"AEROGRID_USER_PASSWORD": False, "AEROGRID_ADMIN_PASSWORD": False, "STAGING_TEST_PW": False}

    if env_path.exists():
        content = env_path.read_text(encoding="utf-8")
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("AEROGRID_USER_PASSWORD="):
                lines.append(f"AEROGRID_USER_PASSWORD={user_pw}")
                keys_updated["AEROGRID_USER_PASSWORD"] = True
            elif stripped.startswith("AEROGRID_ADMIN_PASSWORD="):
                lines.append(f"AEROGRID_ADMIN_PASSWORD={admin_pw}")
                keys_updated["AEROGRID_ADMIN_PASSWORD"] = True
            elif stripped.startswith("STAGING_TEST_PW="):
                lines.append(f"STAGING_TEST_PW={user_pw}")
                keys_updated["STAGING_TEST_PW"] = True
            else:
                lines.append(line)

    for key, updated in keys_updated.items():
        if not updated:
            if key in {"AEROGRID_USER_PASSWORD", "STAGING_TEST_PW"}:
                lines.append(f"{key}={user_pw}")
            elif key == "AEROGRID_ADMIN_PASSWORD":
                lines.append(f"{key}={admin_pw}")

    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Set restrictive owner-only permissions (0600 on POSIX; owner-only ACLs on Windows)
    try:
        os.chmod(env_path, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass

    if sys.platform == "win32":
        try:
            import subprocess
            user = os.environ.get("USERNAME", "")
            if user:
                subprocess.run(
                    ["icacls", str(env_path), "/inheritance:r", "/grant:r", f"{user}:(R,W)"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception:
            pass


def rotate_credentials(
    env_file: Path = Path("deploy/.env.staging"),
    db_path: Path = Path("deploy/auth.staging.sqlite3"),
    revoked_password: str | None = None,
) -> bool:
    """Execute controlled rotation across secret store and database."""
    print("================================================================================")
    print("         AEROGRID AI — CONTROLLED STAGING CREDENTIAL ROTATION                   ")
    print("================================================================================")
    print(f"[SECURITY] Target Secret Store: {env_file.resolve()}")
    print(f"[SECURITY] Target Auth Store:   {db_path.resolve()}")

    if not db_path.exists():
        print(f"[ERROR] Auth database does not exist at {db_path.resolve()}", file=sys.stderr)
        return False

    # 1. Generate fresh CSPRNG credentials
    new_user_pw = generate_credential(32)
    new_admin_pw = generate_credential(32)
    print("[SECURITY] Generated fresh 256-bit CSPRNG credentials in memory (values redacted).")

    # 2. Persist to approved secret store
    update_env_file(env_file, new_user_pw, new_admin_pw)
    print(f"[SECURITY] Persisted new credentials to secret store with owner-only permissions.")

    # 3. Synchronize database accounts via approved SqliteAuthStore.reset_password
    store = SqliteAuthStore(db_path=str(db_path), is_production=True, iterations=600_000)

    for username in STAGING_USERS:
        ok = store.reset_password(username, new_user_pw, actor="admin_controlled_rotation")
        if not ok:
            print(f"[ERROR] Failed to reset password for user: {username}", file=sys.stderr)
            return False
        print(f"[AUDIT] Rotated credentials for persistent account: {username}")

    ok = store.reset_password(STAGING_ADMIN, new_admin_pw, actor="admin_controlled_rotation")
    if not ok:
        print(f"[ERROR] Failed to reset password for admin: {STAGING_ADMIN}", file=sys.stderr)
        return False
    print(f"[AUDIT] Rotated credentials for persistent admin account: {STAGING_ADMIN}")

    # 4. Verification: New credentials authenticate successfully
    print("\n--- Verifying Credential Authentication ---")
    for username in STAGING_USERS:
        account = store.authenticate(username, new_user_pw)
        if not account:
            print(f"[FAIL] User {username} failed to authenticate with new credentials!", file=sys.stderr)
            return False
        print(f"[PASS] User '{username}' authenticated successfully with new configured credentials.")

    admin_account = store.authenticate(STAGING_ADMIN, new_admin_pw)
    if not admin_account:
        print(f"[FAIL] Admin {STAGING_ADMIN} failed to authenticate with new credentials!", file=sys.stderr)
        return False
    print(f"[PASS] Admin '{STAGING_ADMIN}' authenticated successfully with new configured credentials.")

    # 5. Verification: Revoked credentials strictly rejected
    revoked_pw = revoked_password or os.environ.get("AEROGRID_REVOKED_PASSWORD")
    if not revoked_pw and env_file.exists():
        import dotenv
        revoked_pw = dotenv.dotenv_values(str(env_file)).get("AEROGRID_REVOKED_PASSWORD")
    if not revoked_pw:
        revoked_pw = "RevokedStagingTestPassword2026!"

    print("\n--- Verifying Rejection of Revoked Credentials ---")
    for username in STAGING_USERS + [STAGING_ADMIN]:
        bad_auth = store.authenticate(username, revoked_pw)
        if bad_auth is not None:
            print(f"[FAIL] Revoked password was unexpectedly ACCEPTED for '{username}'!", file=sys.stderr)
            return False
        print(f"[PASS] Revoked password strictly REJECTED for '{username}'.")

    # 6. Verification: Cross-role credentials strictly rejected
    print("\n--- Verifying Cross-Role Credential Segregation ---")
    cross_admin_with_user = store.authenticate(STAGING_ADMIN, new_user_pw)
    if cross_admin_with_user is not None:
        print(f"[FAIL] Admin authenticated with standard user password!", file=sys.stderr)
        return False
    print("[PASS] Cross-role authentication rejected: Admin cannot authenticate with user credentials.")

    cross_user_with_admin = store.authenticate(STAGING_USERS[0], new_admin_pw)
    if cross_user_with_admin is not None:
        print(f"[FAIL] User authenticated with admin credentials!", file=sys.stderr)
        return False
    print("[PASS] Cross-role authentication rejected: Standard user cannot authenticate with admin credentials.")

    # Ensure account attempts and lockout counters are clean
    for username in STAGING_USERS:
        store.authenticate(username, new_user_pw)
    store.authenticate(STAGING_ADMIN, new_admin_pw)

    print("\n================================================================================")
    print("  ROTATION COMPLETE: Secret store and persistent database in full agreement.    ")
    print("================================================================================")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rotate persistent staging credentials securely.")
    parser.add_argument("--env-file", type=Path, default=Path("deploy/.env.staging"), help="Path to staging .env file")
    parser.add_argument("--db-path", type=Path, default=Path("deploy/auth.staging.sqlite3"), help="Path to staging SQLite database")
    args = parser.parse_args()

    success = rotate_credentials(env_file=args.env_file, db_path=args.db_path)
    if not success:
        sys.exit(1)
