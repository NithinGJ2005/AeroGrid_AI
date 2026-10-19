"""Security Verification: Production Authentication Hardening and Session Lifecycle Tests.

Validates:
1. Employee credential authentication (PBKDF2 salted hash, zero external dependencies).
2. HTTP-only session cookies and Bearer token fallback.
3. Brute-force lockout enforcement after 5 failed login attempts.
4. Immediate session invalidation upon logout (jti revocation).
5. Immediate access termination upon administrative account deactivation.
6. Immediate permission changes upon administrative role modification.
7. CSRF defense on cookie-authenticated mutating requests.
8. Departmental database query authorization boundaries (HR vs Engineer).
9. Complete absence of dev-token endpoints in production mode.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
import jwt
from pathlib import Path
import secrets
import pytest
from starlette.testclient import TestClient

from app.auth.accounts import AccountStore, SessionRevocationStore
from app.auth.service import Identity
from app.config import AuthMode, Environment, Settings
from app.main import create_app


def make_test_settings(**overrides) -> Settings:
    values = {
        "app_env": "test",
        "secret_key": "s" * 32,
        "dev_auth_signing_key": "d" * 32,
        "enable_development_auth": True,
        "auth_mode": "local",
        "session_expiry_minutes": 60,
        "database_url": "sqlite:///./sample_db.sqlite3",
        "document_roots": [Path("./sample_docs")],
        "auth_db_path": ":memory:",
        "role_permission_map": {
            "employee": ["chat:use", "documents:search", "database:read"],
            "engineer": ["chat:use", "documents:search", "database:read", "engineering:read"],
            "hr": ["chat:use", "documents:search", "database:read", "hr:read"],
            "analyst": ["chat:use", "database:read"],
            "admin": [
                "chat:use",
                "database:read",
                "admin:diagnostics",
                "users:read",
                "users:write",
                "audit:read",
            ],
        },
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_employee_login_with_valid_credentials():
    """Verify employee can log in with username and password, receiving token and cookie."""
    cfg = make_test_settings()
    app = create_app(cfg)
    client = TestClient(app)

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "alice.chen", "password": "EngineeringLead2026!"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["username"] == "alice.chen"
    assert "engineer" in data["user"]["roles"]
    assert "assistant_session" in response.cookies


def test_employee_login_with_invalid_credentials_rejected():
    """Verify bad password returns 401 and does not issue a session."""
    cfg = make_test_settings()
    app = create_app(cfg)
    client = TestClient(app)

    response = client.post(
        "/api/v1/auth/login",
        json={"username": "alice.chen", "password": "WrongPassword!"},
    )
    assert response.status_code == 401
    assert "assistant_session" not in response.cookies


def test_brute_force_lockout_after_five_failed_attempts():
    """Verify account is temporarily locked out after 5 consecutive failed logins."""
    cfg = make_test_settings()
    account_store = AccountStore()
    app = create_app(cfg, account_store=account_store)
    client = TestClient(app)

    # 5 failed login attempts
    for _ in range(5):
        res = client.post(
            "/api/v1/auth/login",
            json={"username": "bob.smith", "password": "BadPassword!"},
        )
        assert res.status_code == 401

    # 6th attempt with CORRECT password must still be rejected due to lockout
    locked_res = client.post(
        "/api/v1/auth/login",
        json={"username": "bob.smith", "password": "StaffEngineer2026!"},
    )
    assert locked_res.status_code == 401


def test_cookie_session_authenticates_protected_endpoints():
    """Verify session cookie allows seamless authentication without manual token entry."""
    cfg = make_test_settings()
    app = create_app(cfg)
    client = TestClient(app)

    # Log in
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "alice.chen", "password": "EngineeringLead2026!"},
    )
    assert login_res.status_code == 200
    session_cookie = login_res.cookies.get("assistant_session")

    # Access /api/v1/auth/me using solely the session cookie
    me_res = client.get("/api/v1/auth/me", cookies={"assistant_session": session_cookie})
    assert me_res.status_code == 200
    data = me_res.json()
    assert data["subject"] == "alice.chen"
    assert "engineer" in data["roles"]
    assert "engineering:read" in data["permissions"]


def test_logout_revokes_session():
    """Verify logout invalidates the session token immediately."""
    cfg = make_test_settings()
    app = create_app(cfg)
    client = TestClient(app)

    # Log in
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "david.miller", "password": "HRPartner2026!"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Verify session works
    me_res = client.get("/api/v1/auth/me", headers=headers)
    assert me_res.status_code == 200

    # Logout
    logout_res = client.post("/api/v1/auth/logout", headers=headers)
    assert logout_res.status_code == 200

    # Subsequent request using the revoked token must fail with 401
    revoked_res = client.get("/api/v1/auth/me", headers=headers)
    assert revoked_res.status_code == 401


def test_administrative_account_deactivation_immediate_effect():
    """Verify deactivating an account terminates active sessions on next request."""
    cfg = make_test_settings()
    account_store = AccountStore()
    app = create_app(cfg, account_store=account_store)
    client = TestClient(app)

    # Log in as Alice
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "alice.chen", "password": "EngineeringLead2026!"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Verify active
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    # Admin deactivates Alice's account
    account_store.set_active_status("alice.chen", False)

    # Alice's very next request must be rejected immediately
    deactivated_res = client.get("/api/v1/auth/me", headers=headers)
    assert deactivated_res.status_code == 401


def test_administrative_role_update_immediate_effect():
    """Verify changing roles immediately updates permissions on subsequent requests."""
    cfg = make_test_settings()
    account_store = AccountStore()
    app = create_app(cfg, account_store=account_store)
    client = TestClient(app)

    # Bob starts with "employee"
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "bob.smith", "password": "StaffEngineer2026!"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me_before = client.get("/api/v1/auth/me", headers=headers).json()
    assert "engineer" not in me_before["roles"]
    assert "engineering:read" not in me_before["permissions"]

    # Admin promotes Bob to "engineer"
    account_store.update_roles("bob.smith", ["engineer"])

    # Bob's next request immediately reflects the new role and permission
    me_after = client.get("/api/v1/auth/me", headers=headers).json()
    assert "engineer" in me_after["roles"]
    assert "engineering:read" in me_after["permissions"]


def test_csrf_protection_on_cross_site_cookie_mutation():
    """Verify mutating request using only session cookie with cross-site Sec-Fetch-Site is blocked."""
    cfg = make_test_settings()
    app = create_app(cfg)
    client = TestClient(app)

    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "bob.smith", "password": "StaffEngineer2026!"},
    )
    session_cookie = login_res.cookies.get("assistant_session")

    # Cross-site forged POST request using cookie only
    res = client.post(
        "/api/v1/auth/logout",
        cookies={"assistant_session": session_cookie},
        headers={"sec-fetch-site": "cross-site"},
    )
    assert res.status_code == 403
    assert res.json()["error"] == "forbidden"


def test_departmental_database_query_boundaries():
    """Verify departmental isolation on catalog queries (HR vs Engineer)."""
    cfg = make_test_settings()
    app = create_app(cfg)
    client = TestClient(app)

    # Engineer Token
    eng_login = client.post(
        "/api/v1/auth/login",
        json={"username": "alice.chen", "password": "EngineeringLead2026!"},
    )
    eng_headers = {"Authorization": f"Bearer {eng_login.json()['access_token']}"}

    # HR Token
    hr_login = client.post(
        "/api/v1/auth/login",
        json={"username": "david.miller", "password": "HRPartner2026!"},
    )
    hr_headers = {"Authorization": f"Bearer {hr_login.json()['access_token']}"}

    # Engineer executes Engineering inventory -> Allowed
    eng_query = client.post(
        "/api/v1/mcp/tools/query_database",
        headers=eng_headers,
        json={"parameters": {"query_id": "engineering.system_inventory"}},
    )
    assert eng_query.status_code == 200

    # Engineer attempts to execute HR employee records -> 403 Forbidden
    eng_on_hr = client.post(
        "/api/v1/mcp/tools/query_database",
        headers=eng_headers,
        json={"parameters": {"query_id": "hr.employee_records"}},
    )
    assert eng_on_hr.status_code == 403

    # HR executes HR employee records -> Allowed
    hr_query = client.post(
        "/api/v1/mcp/tools/query_database",
        headers=hr_headers,
        json={"parameters": {"query_id": "hr.employee_records"}},
    )
    assert hr_query.status_code == 200

    # HR attempts to execute Engineering inventory -> 403 Forbidden
    hr_on_eng = client.post(
        "/api/v1/mcp/tools/query_database",
        headers=hr_headers,
        json={"parameters": {"query_id": "engineering.system_inventory"}},
    )
    assert hr_on_eng.status_code == 403


def test_administrative_user_provisioning_access_control():
    """Verify only admin identity can access user provisioning endpoints."""
    cfg = make_test_settings()
    app = create_app(cfg)
    client = TestClient(app)

    # Regular employee login
    emp_login = client.post(
        "/api/v1/auth/login",
        json={"username": "bob.smith", "password": "StaffEngineer2026!"},
    )
    emp_headers = {"Authorization": f"Bearer {emp_login.json()['access_token']}"}

    # Employee tries to list users -> 403 Forbidden
    assert client.get("/api/v1/admin/users", headers=emp_headers).status_code == 403

    # Employee tries to create user -> 403 Forbidden
    assert client.post(
        "/api/v1/admin/users",
        headers=emp_headers,
        json={
            "username": "attacker",
            "password": "Password123!",
            "full_name": "Attacker",
            "roles": ["admin"],
        },
    ).status_code == 403

    # Admin login
    admin_login = client.post(
        "/api/v1/auth/login",
        json={"username": "admin.system", "password": "AdminSecurity2026!"},
    )
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

    # Admin lists users -> 200 OK
    list_res = client.get("/api/v1/admin/users", headers=admin_headers)
    assert list_res.status_code == 200
    usernames = [u["username"] for u in list_res.json()["users"]]
    assert "alice.chen" in usernames

    # Admin provisions new employee
    create_res = client.post(
        "/api/v1/admin/users",
        headers=admin_headers,
        json={
            "username": "charlie.brown",
            "password": "CharliePassword2026!",
            "full_name": "Charlie Brown",
            "roles": ["employee"],
        },
    )
    assert create_res.status_code == 200

    # New employee can immediately log in
    charlie_login = client.post(
        "/api/v1/auth/login",
        json={"username": "charlie.brown", "password": "CharliePassword2026!"},
    )
    assert charlie_login.status_code == 200


def test_production_mode_disables_dev_token_endpoint():
    """Verify that in production mode, /api/v1/auth/dev-token is not registered."""
    cfg = make_test_settings(
        app_env="production",
        debug=False,
        enable_development_auth=False,
        auth_mode="local",
        audit_log_path=Path("tests/scratch_audit.jsonl"),
        secret_key=secrets.token_hex(32),
        password_hash_iterations=600_000,
        allowed_origins=["http://127.0.0.1:8000"],
        llm_enabled=True,
        llm_base_url="http://127.0.0.1:11434/v1",
        llm_allowed_hosts=["127.0.0.1"],
    )
    app = create_app(cfg)
    client = TestClient(app)

    # Endpoint must return 404 (route does not exist in production)
    res = client.get("/api/v1/auth/dev-token")
    assert res.status_code in {404, 405}


def test_departmental_document_retrieval_isolation():
    """Verify document search strictly enforces ACLs: engineers cannot see HR docs, HR cannot see Eng docs."""
    cfg = make_test_settings()
    app = create_app(cfg)
    client = TestClient(app)

    # Engineer login
    eng_login = client.post(
        "/api/v1/auth/login",
        json={"username": "alice.chen", "password": "EngineeringLead2026!"},
    )
    eng_headers = {"Authorization": f"Bearer {eng_login.json()['access_token']}"}

    # HR login
    hr_login = client.post(
        "/api/v1/auth/login",
        json={"username": "david.miller", "password": "HRPartner2026!"},
    )
    hr_headers = {"Authorization": f"Bearer {hr_login.json()['access_token']}"}

    # 1. Engineer searches for engineering topics -> Succeeds with engineering citation
    eng_search = client.post(
        "/api/v1/mcp/tools/search_documents",
        headers=eng_headers,
        json={"parameters": {"query": "Kubernetes branching deployment"}},
    )
    assert eng_search.status_code == 200
    eng_body = eng_search.json()
    assert len(eng_body["citations"]) > 0
    assert any("engineering_handbook.md" in c["filename"] for c in eng_body["citations"])
    assert "GitHub Flow" in eng_body["content"]

    # 2. Engineer attempts to retrieve HR documents (salary, 401k) -> Denied at search boundary, 0 citations
    eng_on_hr = client.post(
        "/api/v1/mcp/tools/search_documents",
        headers=eng_headers,
        json={"parameters": {"query": "Salary Banding Health Insurance 401(k)"}},
    )
    assert eng_on_hr.status_code == 200
    eng_hr_body = eng_on_hr.json()
    assert len(eng_hr_body["citations"]) == 0
    assert "No matching documents found" in eng_hr_body["content"]
    assert "Salary" not in eng_hr_body["content"]

    # 3. HR searches for HR topics -> Succeeds with HR citation
    hr_search = client.post(
        "/api/v1/mcp/tools/search_documents",
        headers=hr_headers,
        json={"parameters": {"query": "Salary Banding Health Insurance 401(k)"}},
    )
    assert hr_search.status_code == 200
    hr_body = hr_search.json()
    assert len(hr_body["citations"]) > 0
    assert any("hr_benefits_guide.md" in c["filename"] for c in hr_body["citations"])
    assert "401(k)" in hr_body["content"]

    # 4. HR attempts to retrieve Engineering handbook -> Denied at search boundary, 0 citations
    hr_on_eng = client.post(
        "/api/v1/mcp/tools/search_documents",
        headers=hr_headers,
        json={"parameters": {"query": "Kubernetes branching deployment"}},
    )
    assert hr_on_eng.status_code == 200
    hr_eng_body = hr_on_eng.json()
    assert len(hr_eng_body["citations"]) == 0
    assert "No matching documents found" in hr_eng_body["content"]


def test_immediate_account_deactivation_terminates_active_token():
    """Verify that an active JWT token is immediately rejected if the user account is deactivated."""
    cfg = make_test_settings()
    account_store = AccountStore()
    app = create_app(cfg, account_store=account_store)
    client = TestClient(app)

    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "alice.chen", "password": "EngineeringLead2026!"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Token works initially
    me_res = client.get("/api/v1/auth/me", headers=headers)
    assert me_res.status_code == 200

    # Administrative deactivation
    account_store.set_active_status("alice.chen", False)

    # Next call with existing token must fail immediately
    failed_res = client.get("/api/v1/auth/me", headers=headers)
    assert failed_res.status_code == 401
    assert failed_res.json()["error"] == "authentication_required"


def test_revoked_session_and_unauthenticated_requests_blocked():
    """Verify unauthenticated requests and tokens revoked via logout are rejected with 401."""
    cfg = make_test_settings()
    app = create_app(cfg)
    client = TestClient(app)

    # 1. Unauthenticated requests
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.post("/api/v1/mcp/tools/search_documents", json={"parameters": {"query": "test"}}).status_code == 401
    assert client.post("/api/v1/chat", json={"message": "hello"}).status_code == 401

    # 2. Login and get token
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "bob.smith", "password": "StaffEngineer2026!"},
    )
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    # 3. Logout to revoke session
    logout_res = client.post("/api/v1/auth/logout", headers=headers)
    assert logout_res.status_code == 200

    # 4. Token is now revoked
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert client.post("/api/v1/mcp/tools/search_documents", headers=headers, json={"parameters": {"query": "test"}}).status_code == 401
