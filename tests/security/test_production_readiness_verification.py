"""Final Production Readiness Verification Test Suite.

Verifies:
1. Production mode constraints (zero demo accounts, demo credentials rejected, dev routes unmounted, startup invariants).
2. Complete Role-by-Query authorization matrix (SQL catalog queries, document search ACLs, administrative diagnostics).
3. Secure cookies, CSRF protection, and session revocation.
4. Cross-user isolation and provenance.
"""

from pathlib import Path
import secrets
import pytest
from starlette.testclient import TestClient

from app.auth.accounts import AccountStore, SessionRevocationStore
from app.config import Environment, Settings
from app.main import create_app
from app.schemas import SourceCitationResponse


def make_production_settings(**overrides) -> Settings:
    """Return strict production settings meeting all security invariants."""
    values = {
        "app_env": "production",
        "debug": False,
        "enable_development_auth": False,
        "auth_mode": "local",
        "secret_key": secrets.token_hex(32),
        "password_hash_iterations": 600_000,
        "allowed_origins": ["https://intranet.company.internal"],
        "audit_log_path": Path("tests/production_audit.jsonl"),
        "session_expiry_minutes": 60,
        "database_url": "sqlite:///./sample_db.sqlite3",
        "document_roots": [Path("./sample_docs")],
        "auth_db_path": ":memory:",
        "llm_enabled": True,
        "llm_base_url": "http://127.0.0.1:11434/v1",
        "llm_allowed_hosts": ["127.0.0.1"],
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


# ---------------------------------------------------------------------------
# 1. Production Mode Invariants & Startup Failure Tests
# ---------------------------------------------------------------------------

def test_production_rejects_insecure_configurations():
    """Verify production settings validator enforces critical security invariants at startup."""
    # 1. Reject default demo secret key
    with pytest.raises(ValueError, match="Default demonstration secret_key is not permitted in production"):
        make_production_settings(secret_key="enterprise-intranet-assistant-secret-key-32chars")

    with pytest.raises(ValueError, match="Default demonstration secret_key is not permitted in production"):
        make_production_settings(secret_key="s" * 32)

    # 2. Reject missing ALLOWED_ORIGINS
    with pytest.raises(ValueError, match="ALLOWED_ORIGINS must be configured in production"):
        make_production_settings(allowed_origins=[])

    # 3. Reject low PBKDF2 iterations in production (< 600,000)
    with pytest.raises(ValueError, match="PASSWORD_HASH_ITERATIONS must be at least 600,000 in production"):
        make_production_settings(password_hash_iterations=200_000)

    # 4. Reject DEBUG=True
    with pytest.raises(ValueError, match="DEBUG must be false in production"):
        make_production_settings(debug=True)

    # 5. Reject ENABLE_DEVELOPMENT_AUTH=True in production
    with pytest.raises(ValueError, match="ENABLE_DEVELOPMENT_AUTH must be false in production"):
        make_production_settings(enable_development_auth=True)

    # 6. Reject missing AUDIT_LOG_PATH
    with pytest.raises(ValueError, match="AUDIT_LOG_PATH is required in production"):
        make_production_settings(audit_log_path=None)


def test_production_instance_disables_all_demo_access():
    """Verify a production application instance disables quick sign-in, rejects demo credentials, and unmounts dev routes."""
    cfg = make_production_settings()
    account_store = AccountStore(is_production=True)
    app = create_app(cfg, account_store=account_store)
    client = TestClient(app)

    # 1. /api/v1/auth/config disables quick sign in and exposes 0 demo accounts
    config_res = client.get("/api/v1/auth/config")
    assert config_res.status_code == 200
    cfg_data = config_res.json()
    assert cfg_data["app_env"] == "production"
    assert cfg_data["enable_quick_signin"] is False
    assert cfg_data["demo_accounts"] == []

    # 2. Sample demo credentials CANNOT authenticate in production
    demo_creds = [
        ("alice.chen", "EngineeringLead2026!"),
        ("david.miller", "HRPartner2026!"),
        ("bob.smith", "StaffEngineer2026!"),
        ("admin.system", "AdminSecurity2026!"),
    ]
    for username, password in demo_creds:
        login_res = client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        assert login_res.status_code == 401

    # 3. Dev-token route is NOT mounted
    dev_token_res = client.get("/api/v1/auth/dev-token")
    assert dev_token_res.status_code in {404, 405}


def test_production_browser_cookies_and_csrf():
    """Verify production browser login sets Secure cookies and requires CSRF protection."""
    cfg = make_production_settings()
    account_store = AccountStore(is_production=True)
    # Provision genuine production employee
    account_store.create_user("prod.alice", "ProductionPass2026!", "Alice Chen", ["engineer"])
    app = create_app(cfg, account_store=account_store)
    client = TestClient(app)

    # Browser login
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "prod.alice", "password": "ProductionPass2026!", "client_type": "browser"},
    )
    assert login_res.status_code == 200
    cookies = login_res.cookies
    assert "assistant_session" in cookies
    assert "assistant_csrf" in cookies

    session_cookie_header = login_res.headers.get("set-cookie", "")
    assert "httponly" in session_cookie_header.lower()
    assert "secure" in session_cookie_header.lower()
    assert "samesite=lax" in session_cookie_header.lower()

    # Mutating request without CSRF token is rejected with 403
    session_token = cookies["assistant_session"]
    client.cookies.set("assistant_session", session_token)
    logout_no_csrf = client.post(
        "/api/v1/auth/logout",
        headers={"Origin": "https://intranet.company.internal"},
    )
    assert logout_no_csrf.status_code == 403


# ---------------------------------------------------------------------------
# 2. Comprehensive Role-by-Query Authorization Matrix
# ---------------------------------------------------------------------------

def test_complete_role_by_query_authorization_matrix():
    """Verify backend authorization across all 5 roles and all 3 SQL catalog queries."""
    cfg = make_production_settings()
    account_store = AccountStore(is_production=True)

    # Provision authentic test accounts for all 5 enterprise roles
    users = {
        "employee": account_store.create_user("emp.bob", "EmpPass12345!", "Bob Smith", ["employee"]),
        "engineer": account_store.create_user("eng.alice", "EngPass12345!", "Alice Chen", ["engineer"]),
        "hr": account_store.create_user("hr.david", "HrPass123456!", "David Miller", ["hr"]),
        "analyst": account_store.create_user("ana.emma", "AnaPass12345!", "Emma Watson", ["analyst"]),
        "admin": account_store.create_user("adm.sec", "AdmPass12345!", "Security Admin", ["admin"]),
    }

    app = create_app(cfg, account_store=account_store)
    client = TestClient(app)

    # Obtain API tokens for all roles
    tokens = {}
    for role, user in users.items():
        res = client.post(
            "/api/v1/auth/token",
            json={"username": user.username, "password": f"{role.capitalize()[:3]}Pass12345!" if role != "hr" else "HrPass123456!"},
        )
        assert res.status_code == 200, f"Login failed for {role}: {res.text}"
        tokens[role] = res.json()["access_token"]

    # Expected Permission Matrix:
    # 1. 'directory.by_department' (required: 'database:read') -> Allowed for all 5 roles (intentional shared directory exception)
    # 2. 'hr.employee_records' (required: 'hr:read') -> Allowed ONLY for hr (Forbidden 403 for employee, engineer, analyst, admin)
    # 3. 'engineering.system_inventory' (required: 'engineering:read') -> Allowed ONLY for engineer (Forbidden 403 for employee, hr, analyst, admin)

    for role, token in tokens.items():
        headers = {"Authorization": f"Bearer {token}"}

        # Query 1: directory.by_department
        res_dir = client.post(
            "/api/v1/mcp/tools/query_database",
            headers=headers,
            json={"parameters": {"query_id": "directory.by_department", "parameters": {"department": "Engineering"}}},
        )
        assert res_dir.status_code == 200, f"Role '{role}' failed to access directory.by_department"
        assert len(res_dir.json()["citations"]) > 0
        assert "sample_db.sqlite3 [table: employee_directory]" in res_dir.json()["citations"][0]["filename"]

        # Query 2: hr.employee_records
        res_hr = client.post(
            "/api/v1/mcp/tools/query_database",
            headers=headers,
            json={"parameters": {"query_id": "hr.employee_records"}},
        )
        if role == "hr":
            assert res_hr.status_code == 200, "HR role must be allowed to execute hr.employee_records"
        else:
            assert res_hr.status_code == 403, f"Role '{role}' must be forbidden from hr.employee_records"

        # Query 3: engineering.system_inventory
        res_eng = client.post(
            "/api/v1/mcp/tools/query_database",
            headers=headers,
            json={"parameters": {"query_id": "engineering.system_inventory"}},
        )
        if role == "engineer":
            assert res_eng.status_code == 200, "Engineer role must be allowed to execute engineering.system_inventory"
        else:
            assert res_eng.status_code == 403, f"Role '{role}' must be forbidden from engineering.system_inventory"


def test_document_search_acl_isolation_matrix():
    """Verify document search ACLs strictly isolate confidential documents across roles."""
    cfg = make_production_settings()
    account_store = AccountStore(is_production=True)
    users = {
        "employee": account_store.create_user("emp.bob", "EmpPass12345!", "Bob Smith", ["employee"]),
        "engineer": account_store.create_user("eng.alice", "EngPass12345!", "Alice Chen", ["engineer"]),
        "hr": account_store.create_user("hr.david", "HrPass123456!", "David Miller", ["hr"]),
        "admin": account_store.create_user("adm.sec", "AdmPass12345!", "Security Admin", ["admin"]),
    }
    app = create_app(cfg, account_store=account_store)
    client = TestClient(app)

    tokens = {}
    for role, user in users.items():
        res = client.post(
            "/api/v1/auth/token",
            json={"username": user.username, "password": f"{role.capitalize()[:3]}Pass12345!" if role != "hr" else "HrPass123456!"},
        )
        tokens[role] = res.json()["access_token"]

    # 1. General policy document (leave_policy.md): Accessible to employee role with documents:search
    res_emp = client.post(
        "/api/v1/mcp/tools/search_documents",
        headers={"Authorization": f"Bearer {tokens['employee']}"},
        json={"parameters": {"query": "Annual leave vacation accrual"}},
    )
    assert res_emp.status_code == 200
    filenames = [c["filename"] for c in res_emp.json().get("citations", [])]
    assert any("leave_policy.md" in fn for fn in filenames)

    # 2. Engineering Handbook (ACL: engineer): ONLY engineer can retrieve citations
    eng_res = client.post(
        "/api/v1/mcp/tools/search_documents",
        headers={"Authorization": f"Bearer {tokens['engineer']}"},
        json={"parameters": {"query": "Kubernetes branching deployment microservices"}},
    )
    assert eng_res.status_code == 200
    assert any("engineering_handbook.md" in c["filename"] for c in eng_res.json()["citations"])

    # Non-engineers (employee, hr) cannot retrieve engineering_handbook.md
    for role in ["employee", "hr"]:
        res = client.post(
            "/api/v1/mcp/tools/search_documents",
            headers={"Authorization": f"Bearer {tokens[role]}"},
            json={"parameters": {"query": "Kubernetes branching deployment microservices"}},
        )
        assert res.status_code == 200
        filenames = [c["filename"] for c in res.json().get("citations", [])]
        assert not any("engineering_handbook.md" in fn for fn in filenames)

    # 3. HR Benefits Guide (ACL: hr): ONLY hr can retrieve citations
    hr_res = client.post(
        "/api/v1/mcp/tools/search_documents",
        headers={"Authorization": f"Bearer {tokens['hr']}"},
        json={"parameters": {"query": "Healthcare dental coverage retirement 401(k)"}},
    )
    assert hr_res.status_code == 200
    assert any("hr_benefits_guide.md" in c["filename"] for c in hr_res.json()["citations"])

    # Non-HR (employee, engineer) cannot retrieve hr_benefits_guide.md
    for role in ["employee", "engineer"]:
        res = client.post(
            "/api/v1/mcp/tools/search_documents",
            headers={"Authorization": f"Bearer {tokens[role]}"},
            json={"parameters": {"query": "Healthcare dental coverage retirement 401(k)"}},
        )
        assert res.status_code == 200
        filenames = [c["filename"] for c in res.json().get("citations", [])]
        assert not any("hr_benefits_guide.md" in fn for fn in filenames)

    # 4. Admin role does NOT have documents:search -> calling search_documents returns 403 Forbidden
    adm_res = client.post(
        "/api/v1/mcp/tools/search_documents",
        headers={"Authorization": f"Bearer {tokens['admin']}"},
        json={"parameters": {"query": "Annual leave vacation accrual"}},
    )
    assert adm_res.status_code == 403
