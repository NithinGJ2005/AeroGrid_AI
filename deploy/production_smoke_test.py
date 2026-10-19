"""Dedicated isolated production instance smoke test.

Spawns an isolated Uvicorn instance strictly under APP_ENV=production with:
1. Dynamically generated ephemeral 256-bit CSPRNG secret (no static hardcoded keys).
2. Clean, isolated environment variables without relying on dev .env defaults.
3. Intended HTTPS deployment origin validation (https://intranet.company.internal).
4. Secure, HttpOnly, SameSite cookie verification.
5. CSRF origin and double-submit token enforcement.
6. Zero demo accounts, demo credential rejection, and dev route isolation.
7. Session invalidation on logout.
"""

import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import requests

from app.auth.accounts import SqliteAuthStore

PROD_HOST = "127.0.0.1"
PROD_PORT = "8001"
PROD_URL = f"http://{PROD_HOST}:{PROD_PORT}"
HTTPS_ORIGIN = "https://intranet.company.internal"


def setup_production_db(admin_password: str, db_path: Path):
    if db_path.exists():
        db_path.unlink()
    # Create production auth store and provision one genuine production security admin
    store = SqliteAuthStore(db_path=str(db_path), is_production=True, iterations=600_000)
    store.create_user(
        username="corp.admin",
        password=admin_password,
        full_name="Corporate Security Administrator",
        roles=["admin"],
    )
    print("Provisioned genuine production user 'corp.admin'.")


def run_smoke_test():
    # Use isolated temporary directory for test DB and audit logs
    temp_dir = Path(tempfile.mkdtemp(prefix="prod_smoke_")).resolve()
    db_path = temp_dir / "prod_live_auth.sqlite3"
    audit_path = temp_dir / "prod_live_audit.jsonl"

    # Generate a fresh ephemeral password for this smoke-test run
    smoke_admin_password = secrets.token_urlsafe(32)
    setup_production_db(smoke_admin_password, db_path)

    # Generate an ephemeral cryptographically random 256-bit secret key
    ephemeral_secret = secrets.token_hex(32)
    print("[SECURITY] Generated fresh ephemeral 256-bit CSPRNG production secret in memory (secret value strictly omitted from logs).")

    # Explicit, isolated production environment dictionary (do not inherit dev env vars or .env defaults)
    clean_env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": ".",
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", "C:\\Windows"),
        "TEMP": str(temp_dir),
        "TMP": str(temp_dir),
        "APP_ENV": "production",
        "ENABLE_DEVELOPMENT_AUTH": "false",
        "DEBUG": "false",
        "SECRET_KEY": ephemeral_secret,
        "PASSWORD_HASH_ITERATIONS": "600000",
        "ALLOWED_ORIGINS": f'["{HTTPS_ORIGIN}"]',
        "AUTH_MODE": "local",
        "HOST": PROD_HOST,
        "PORT": PROD_PORT,
        "AUTH_DB_PATH": str(db_path),
        "AUDIT_LOG_PATH": str(audit_path),
        "DATABASE_URL": "sqlite:///./sample_db.sqlite3",
        "DOCUMENT_ROOTS": '["./sample_docs"]',
        "LLM_ENABLED": "true",
        "LLM_BASE_URL": "http://127.0.0.1:11434/v1",
        "LLM_ALLOWED_HOSTS": '["127.0.0.1"]',
        "ROLE_PERMISSION_MAP": '{"employee": ["chat:use", "documents:search", "database:read"], "engineer": ["chat:use", "documents:search", "database:read", "engineering:read"], "hr": ["chat:use", "documents:search", "database:read", "hr:read"], "analyst": ["chat:use", "database:read"], "admin": ["chat:use", "database:read", "admin:diagnostics", "users:read", "users:write", "audit:read"]}',
    }

    print(f"Starting dedicated production Uvicorn server on port {PROD_PORT}...")
    server_cmd = [
        sys.executable,
        "-m", "uvicorn",
        "app.main:create_app",
        "--factory",
        "--host", PROD_HOST,
        "--port", PROD_PORT,
    ]
    proc = subprocess.Popen(server_cmd, env=clean_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    try:
        # Wait for server to become ready
        ready = False
        for _ in range(30):
            try:
                r = requests.get(f"{PROD_URL}/health/live", timeout=1)
                if r.status_code == 200:
                    ready = True
                    break
            except Exception:
                time.sleep(0.5)

        assert ready, "Production server failed to become ready"
        print("Production server is ready and serving requests.")

        s = requests.Session()

        # 1. Verify /api/v1/auth/config in production
        print("\n--- Test 1: Production Auth Config ---")
        cfg_res = s.get(f"{PROD_URL}/api/v1/auth/config", timeout=5)
        assert cfg_res.status_code == 200
        cfg_data = cfg_res.json()
        print("Production Auth Config:", cfg_data)
        assert cfg_data["app_env"] == "production"
        assert cfg_data["enable_quick_signin"] is False
        assert cfg_data["demo_accounts"] == []
        print("[PASS] Quick Sign In disabled and demo accounts list is empty.")

        # 2. Verify sample demo credentials CANNOT authenticate
        print("\n--- Test 2: Demo Credentials Rejection ---")
        demo_login = s.post(
            f"{PROD_URL}/api/v1/auth/login",
            json={"username": "alice.chen", "password": "EngineeringLead2026!"},
            timeout=5,
        )
        print("Demo login status code:", demo_login.status_code)
        assert demo_login.status_code == 401
        print("[PASS] Demo account credentials rejected with 401.")

        # 3. Verify /api/v1/auth/dev-token route is NOT mounted
        print("\n--- Test 3: Dev-token Route Unmounted ---")
        dev_token_res = s.get(f"{PROD_URL}/api/v1/auth/dev-token", timeout=5)
        print("Dev-token route status code:", dev_token_res.status_code)
        assert dev_token_res.status_code in {404, 405}
        print("[PASS] Dev-token endpoint not mounted in production.")

        # 4. Authenticate genuine production user with browser client_type and HTTPS origin
        print("\n--- Test 4: Genuine Production Login & Secure Cookie Headers ---")
        login_res = s.post(
            f"{PROD_URL}/api/v1/auth/login",
            headers={"Origin": HTTPS_ORIGIN},
            json={
                "username": "corp.admin",
                "password": smoke_admin_password,
                "client_type": "browser",
            },
            timeout=5,
        )
        assert login_res.status_code == 200
        set_cookie_raw = login_res.headers.get("Set-Cookie", "")
        assert "httponly" in set_cookie_raw.lower()
        assert "secure" in set_cookie_raw.lower()
        assert "samesite=lax" in set_cookie_raw.lower()
        print("[SECURITY] Set-Cookie header validated (raw session/csrf tokens strictly redacted from logs).")
        print("[PASS] Session cookie has HttpOnly, Secure, and SameSite=Lax flags.")

        # Extract tokens for manual forwarding test (since requests library enforces RFC 6265 and refuses to send Secure cookies over plain http)
        session_token = login_res.cookies.get("assistant_session")
        csrf_token = login_res.cookies.get("assistant_csrf")
        assert session_token and csrf_token

        # 5. Verify CSRF protection for cookie-authenticated mutating requests
        print("\n--- Test 5: CSRF Protection & HTTPS Origin Binding ---")
        # 5a. Mutating request with localhost HTTP origin -> 403 Forbidden (verifies localhost cannot enter production config)
        localhost_logout = requests.post(
            f"{PROD_URL}/api/v1/auth/logout",
            headers={
                "Origin": PROD_URL,
                "Cookie": f"assistant_session={session_token}; assistant_csrf={csrf_token}",
                "X-CSRF-Token": csrf_token,
            },
            timeout=5,
        )
        print("Logout from localhost HTTP origin status:", localhost_logout.status_code)
        assert localhost_logout.status_code == 403
        print("[PASS] Localhost HTTP origin strictly rejected with 403 Forbidden.")

        # 5b. Mutating request with untrusted external origin -> 403 Forbidden
        untrusted_logout = requests.post(
            f"{PROD_URL}/api/v1/auth/logout",
            headers={
                "Origin": "https://malicious-external-site.org",
                "Cookie": f"assistant_session={session_token}; assistant_csrf={csrf_token}",
                "X-CSRF-Token": csrf_token,
            },
            timeout=5,
        )
        print("Logout from untrusted origin status:", untrusted_logout.status_code)
        assert untrusted_logout.status_code == 403
        print("[PASS] Untrusted external origin blocked with 403 Forbidden.")

        # 5b. Mutating request with plaintext HTTP version of intranet origin -> 403 Forbidden
        http_insecure_logout = requests.post(
            f"{PROD_URL}/api/v1/auth/logout",
            headers={
                "Origin": "http://intranet.company.internal",
                "Cookie": f"assistant_session={session_token}; assistant_csrf={csrf_token}",
                "X-CSRF-Token": csrf_token,
            },
            timeout=5,
        )
        print("Logout from insecure plaintext HTTP origin status:", http_insecure_logout.status_code)
        assert http_insecure_logout.status_code == 403
        print("[PASS] Insecure plaintext HTTP origin blocked with 403 Forbidden.")

        # 5c. Mutating request with HTTPS origin but missing CSRF token header -> 403 Forbidden
        missing_csrf_logout = requests.post(
            f"{PROD_URL}/api/v1/auth/logout",
            headers={
                "Origin": HTTPS_ORIGIN,
                "Cookie": f"assistant_session={session_token}",
            },
            timeout=5,
        )
        print("Logout missing CSRF token header status:", missing_csrf_logout.status_code)
        assert missing_csrf_logout.status_code == 403
        print("[PASS] Request missing anti-CSRF token rejected with 403 Forbidden.")

        # 5d. Mutating request with valid HTTPS origin and matching double-submit CSRF token -> 200 OK
        valid_logout = requests.post(
            f"{PROD_URL}/api/v1/auth/logout",
            headers={
                "Origin": HTTPS_ORIGIN,
                "Cookie": f"assistant_session={session_token}; assistant_csrf={csrf_token}",
                "X-CSRF-Token": csrf_token,
            },
            timeout=5,
        )
        print("Logout with valid HTTPS origin and CSRF token status:", valid_logout.status_code)
        assert valid_logout.status_code == 200
        print("[PASS] Logout succeeded with valid HTTPS origin and anti-CSRF token.")

        # 6. Verify session invalidated in backend revocation store
        print("\n--- Test 6: Invalidation Verification ---")
        me_res = requests.get(
            f"{PROD_URL}/api/v1/auth/me",
            headers={"Cookie": f"assistant_session={session_token}"},
            timeout=5,
        )
        print("Subsequent /auth/me status:", me_res.status_code)
        assert me_res.status_code == 401
        print("[PASS] Revoked session token rejected with 401.")

        print("\n=======================================================")
        print("  ALL ISOLATED PRODUCTION SMOKE TESTS PASSED!         ")
        print("=======================================================")

    finally:
        print("\nShutting down production test server...")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        print("Production test server stopped.")

        # Clean up temporary database and audit log directory
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
            print("Temporary smoke test artifacts cleaned up.")

if __name__ == "__main__":
    run_smoke_test()
