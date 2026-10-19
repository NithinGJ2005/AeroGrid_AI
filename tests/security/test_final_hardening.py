"""Regression tests for final authentication, authorization, and data-correctness hardening.

Covers:
1. Removal of development login shortcuts and demo credentials in production.
2. Account switching with genuine logout and session invalidation.
3. Least-privilege separation of administrative diagnostics from business data (HR/Engineering).
4. Employee directory exact department filtering, data fidelity, and citation provenance.
5. Production configuration security invariant enforcement.
"""

from __future__ import annotations

import json
from pathlib import Path
import secrets

import pytest
from starlette.testclient import TestClient

from app.auth.accounts import SqliteAuthStore, hash_password
from app.auth.service import Identity
from app.config import Environment, Settings
from app.db.catalog import SAMPLE_QUERY_CATALOG
from app.db.service import DatabaseQueryService
from app.documents.service import DocumentIndexer
from app.llm.service import GenerationResult, LocalLLMClient
from app.main import create_app
from app.orchestration.mcp import DatabaseQueryMCPTool, DocumentSearchMCPTool, MCPToolRegistry
from app.orchestration.service import IntranetAssistantService


def make_settings(**overrides) -> Settings:
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
        "password_hash_iterations": 100_000,
        "allowed_origins": ["http://127.0.0.1:8000", "http://localhost:8000"],
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
# 1. Removal of development shortcuts & credentials in production
# ---------------------------------------------------------------------------

def test_production_removes_demo_shortcuts_and_credentials():
    """Verify production mode hides demo accounts, refuses demo passwords, and drops dev endpoints."""
    # 1. Check /api/v1/auth/config in production
    prod_cfg = make_settings(
        app_env="production",
        secret_key=secrets.token_hex(32),
        enable_development_auth=False,
        audit_log_path=Path("./test_audit.log"),
        llm_enabled=True,
        llm_base_url="http://127.0.0.1:11434/v1",
        llm_allowed_hosts=["127.0.0.1"],
        password_hash_iterations=600_000,
    )
    prod_app = create_app(prod_cfg)
    client = TestClient(prod_app)

    res = client.get("/api/v1/auth/config")
    assert res.status_code == 200
    data = res.json()
    assert data["app_env"] == "production"
    assert data["enable_quick_signin"] is False
    assert len(data["demo_accounts"]) == 0

    # 2. Verify dev-token endpoint is NOT mounted in production
    assert client.get("/api/v1/auth/dev-token").status_code == 404

    # 3. Verify SqliteAuthStore in production does not seed demo accounts
    prod_store = SqliteAuthStore(db_path=":memory:", is_production=True)
    assert len(prod_store.list_users()) == 0

    # 4. Even if an account was seeded previously, sample demo passwords are strictly rejected in production
    prod_store.create_user("alice.chen", "NonDemoSecurePass2026!", "Alice Chen", ["engineer"])
    # Attempting to use known demo password fails
    assert prod_store.authenticate("alice.chen", "EngineeringLead2026!") is None
    # Real password succeeds
    assert prod_store.authenticate("alice.chen", "NonDemoSecurePass2026!") is not None


def test_development_mode_exposes_demo_config():
    """Verify development mode cleanly exposes quick sign-in config when enabled."""
    dev_cfg = make_settings()
    app = create_app(dev_cfg)
    client = TestClient(app)

    res = client.get("/api/v1/auth/config")
    assert res.status_code == 200
    data = res.json()
    assert data["enable_quick_signin"] is True
    assert len(data["demo_accounts"]) >= 4
    usernames = [a["username"] for a in data["demo_accounts"]]
    assert "alice.chen" in usernames
    assert "admin.system" in usernames


# ---------------------------------------------------------------------------
# 2. Account-switching with genuine session invalidation
# ---------------------------------------------------------------------------

def test_account_switching_invalidates_session_and_clears_access():
    """Verify switching employee terminates prior session on backend, preventing reuse."""
    cfg = make_settings()
    app = create_app(cfg)
    client = TestClient(app)

    # 1. Alice logs in as browser client
    alice_login = client.post(
        "/api/v1/auth/login",
        json={"username": "alice.chen", "password": "EngineeringLead2026!", "client_type": "browser"},
    )
    assert alice_login.status_code == 200
    session_cookie = alice_login.cookies.get("assistant_session")
    csrf_cookie = alice_login.cookies.get("assistant_csrf")
    assert session_cookie is not None
    assert csrf_cookie is not None

    # Alice accesses /api/v1/auth/me
    assert client.get("/api/v1/auth/me", cookies={"assistant_session": session_cookie}).status_code == 200

    # 2. Alice switches account: genuine logout
    logout_res = client.post(
        "/api/v1/auth/logout",
        cookies={"assistant_session": session_cookie, "assistant_csrf": csrf_cookie},
        headers={"Origin": "http://127.0.0.1:8000", "X-CSRF-Token": csrf_cookie},
    )
    assert logout_res.status_code == 200

    # 3. Alice's old session cookie is now revoked in durable storage
    me_after_logout = client.get("/api/v1/auth/me", cookies={"assistant_session": session_cookie})
    assert me_after_logout.status_code == 401

    # 4. Bob logs in as browser client
    bob_login = client.post(
        "/api/v1/auth/login",
        json={"username": "bob.smith", "password": "StaffEngineer2026!", "client_type": "browser"},
    )
    assert bob_login.status_code == 200
    bob_session = bob_login.cookies.get("assistant_session")

    # Bob's identity is active and distinct
    bob_me = client.get("/api/v1/auth/me", cookies={"assistant_session": bob_session}).json()
    assert bob_me["subject"] == "bob.smith"
    assert "engineer" not in bob_me["roles"]


# ---------------------------------------------------------------------------
# 3. Least-privilege separation of administrative diagnostics from business data
# ---------------------------------------------------------------------------

def test_admin_least_privilege_denied_hr_and_engineering_records():
    """Verify security admin cannot read HR records, engineering inventory, or department documents."""
    cfg = make_settings()
    app = create_app(cfg)
    client = TestClient(app)

    # Admin logs in
    admin_login = client.post(
        "/api/v1/auth/token",
        json={"username": "admin.system", "password": "AdminSecurity2026!"},
    )
    assert admin_login.status_code == 200
    admin_token = admin_login.json()["access_token"]
    admin_h = {"Authorization": f"Bearer {admin_token}"}

    # 1. Verify admin permissions: includes diagnostic & user management, EXCLUDES hr:read and engineering:read
    me_data = client.get("/api/v1/auth/me", headers=admin_h).json()
    assert "admin" in me_data["roles"]
    assert "admin:diagnostics" in me_data["permissions"]
    assert "users:read" in me_data["permissions"]
    assert "users:write" in me_data["permissions"]
    assert "audit:read" in me_data["permissions"]
    assert "hr:read" not in me_data["permissions"]
    assert "engineering:read" not in me_data["permissions"]

    # 2. Admin cannot access HR database query -> 403 Forbidden
    hr_db_res = client.post(
        "/api/v1/mcp/tools/query_database",
        headers=admin_h,
        json={"parameters": {"query_id": "hr.employee_records"}},
    )
    assert hr_db_res.status_code == 403

    # 3. Admin cannot access Engineering inventory database query -> 403 Forbidden
    eng_db_res = client.post(
        "/api/v1/mcp/tools/query_database",
        headers=admin_h,
        json={"parameters": {"query_id": "engineering.system_inventory"}},
    )
    assert eng_db_res.status_code == 403

    # 4. Admin does not have documents:search -> calling search_documents returns 403 Forbidden
    admin_doc_res = client.post(
        "/api/v1/mcp/tools/search_documents",
        headers=admin_h,
        json={"parameters": {"query": "Kubernetes branching deployment microservices"}},
    )
    assert admin_doc_res.status_code == 403

    # 5. Non-engineering employee (bob.smith) has documents:search, but document ACL denies engineering_handbook.md
    bob_login = client.post(
        "/api/v1/auth/token",
        json={"username": "bob.smith", "password": "StaffEngineer2026!"},
    )
    assert bob_login.status_code == 200
    bob_h = {"Authorization": f"Bearer {bob_login.json()['access_token']}"}

    eng_doc_res = client.post(
        "/api/v1/mcp/tools/search_documents",
        headers=bob_h,
        json={"parameters": {"query": "Kubernetes branching deployment microservices"}},
    )
    assert eng_doc_res.status_code == 200
    # No citations from engineering_handbook.md returned for non-engineer
    for c in eng_doc_res.json().get("citations", []):
        assert "engineering_handbook.md" not in c["filename"]

    # 6. Non-HR engineer (alice.chen) has documents:search, but document ACL denies hr_benefits_guide.md
    alice_login = client.post(
        "/api/v1/auth/token",
        json={"username": "alice.chen", "password": "EngineeringLead2026!"},
    )
    assert alice_login.status_code == 200
    alice_h = {"Authorization": f"Bearer {alice_login.json()['access_token']}"}

    hr_doc_res = client.post(
        "/api/v1/mcp/tools/search_documents",
        headers=alice_h,
        json={"parameters": {"query": "Healthcare dental coverage retirement 401(k)"}},
    )
    assert hr_doc_res.status_code == 200
    for c in hr_doc_res.json().get("citations", []):
        assert "hr_benefits_guide.md" not in c["filename"]

    # 7. Admin CAN access general employee directory (public catalog query)
    dir_res = client.post(
        "/api/v1/mcp/tools/query_database",
        headers=admin_h,
        json={"parameters": {"query_id": "directory.by_department", "parameters": {"department": "Engineering"}}},
    )
    assert dir_res.status_code == 200
    assert len(dir_res.json()["citations"]) > 0


# ---------------------------------------------------------------------------
# 4. Employee-directory filtering, data fidelity & citation provenance
# ---------------------------------------------------------------------------

def test_department_directory_exact_filtering_and_provenance():
    """Verify 'Data Engineering' returns 0 rows without silent broadening, while 'Engineering' returns records."""
    cfg = make_settings()
    app = create_app(cfg)
    client = TestClient(app)

    # Bob (employee role) logs in
    emp_login = client.post(
        "/api/v1/auth/token",
        json={"username": "bob.smith", "password": "StaffEngineer2026!"},
    )
    emp_h = {"Authorization": f"Bearer {emp_login.json()['access_token']}"}

    # 1. Query for 'Data Engineering' (distinct department not present in employee_directory)
    data_eng_res = client.post(
        "/api/v1/mcp/tools/query_database",
        headers=emp_h,
        json={"parameters": {"query_id": "directory.by_department", "parameters": {"department": "Data Engineering"}}},
    )
    assert data_eng_res.status_code == 200
    parsed_data = json.loads(data_eng_res.json()["content"])
    assert len(parsed_data["rows"]) == 0
    # No citations generated when 0 rows match
    assert len(data_eng_res.json()["citations"]) == 0

    # 2. Query for 'Engineering' (legitimately contains Alice Chen and Bob Smith)
    eng_res = client.post(
        "/api/v1/mcp/tools/query_database",
        headers=emp_h,
        json={"parameters": {"query_id": "directory.by_department", "parameters": {"department": "Engineering"}}},
    )
    assert eng_res.status_code == 200
    eng_parsed = json.loads(eng_res.json()["content"])
    assert len(eng_parsed["rows"]) == 2
    names = [row["display_name"] for row in eng_parsed["rows"]]
    assert "Alice Chen" in names
    assert "Bob Smith" in names

    # Accurate citation with table provenance is generated
    citations = eng_res.json()["citations"]
    assert len(citations) == 1
    assert "sample_db.sqlite3" in citations[0]["filename"]
    assert "employee_directory" in citations[0]["filename"]


def test_chat_response_includes_accurate_tool_trace():
    """Verify chat endpoint returns accurate execution tool trace rather than frontend guessing."""
    cfg = make_settings()

    class ScriptedCatalogLLM(LocalLLMClient):
        def __init__(self):
            pass
        def generate(self, messages, max_tokens=None, temperature=None):
            # If system/user message asks for directory, call tool
            last_msg = messages[-1].content
            if "tool result" in last_msg.lower():
                return GenerationResult(
                    content="The employee directory for Engineering lists Alice Chen and Bob Smith.",
                    model="mock",
                    prompt_tokens=10,
                    completion_tokens=10,
                )
            return GenerationResult(
                content='{"tool": "query_database", "parameters": {"query_id": "directory.by_department", "parameters": {"department": "Engineering"}}}',
                model="mock",
                prompt_tokens=10,
                completion_tokens=10,
            )

    app = create_app(cfg)
    app.state.assistant_service = IntranetAssistantService(
        cfg, ScriptedCatalogLLM(), app.state.tool_registry, app.state.audit_sink
    )
    client = TestClient(app)

    # Bob logs in
    login_res = client.post("/api/v1/auth/token", json={"username": "bob.smith", "password": "StaffEngineer2026!"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    chat_res = client.post(
        "/api/v1/chat",
        headers=headers,
        json={"message": "Show me the employee directory for the Engineering department"},
    )
    assert chat_res.status_code == 200
    body = chat_res.json()
    assert body["tool_trace"] is not None
    assert "directory.by_department" in body["tool_trace"]
    assert "employee_directory table" in body["tool_trace"]
    assert len(body["citations"]) == 1
    assert "sample_db.sqlite3" in body["citations"][0]["filename"]


# ---------------------------------------------------------------------------
# 5. Production configuration security invariant enforcement
# ---------------------------------------------------------------------------

def test_production_rejects_insecure_configuration():
    """Verify production settings validator enforces critical security invariants."""
    base_prod = {
        "app_env": "production",
        "secret_key": "enterprise-intranet-assistant-secret-key-32chars",  # Default demonstration key
        "enable_development_auth": False,
        "auth_mode": "local",
        "audit_log_path": Path("./prod_audit.log"),
        "llm_enabled": True,
        "llm_base_url": "http://127.0.0.1:11434/v1",
        "llm_allowed_hosts": ["127.0.0.1"],
        "password_hash_iterations": 600_000,
        "allowed_origins": ["https://intranet.company.internal"],
    }

    # 1. Default demo secret_key rejected in production
    with pytest.raises(ValueError, match="Default demonstration secret_key is not permitted"):
        Settings(_env_file=None, **base_prod)

    # 2. Low iterations (< 600,000) rejected in production
    low_iter = dict(base_prod)
    low_iter["secret_key"] = "R" * 32
    low_iter["password_hash_iterations"] = 100_000
    with pytest.raises(ValueError, match="PASSWORD_HASH_ITERATIONS must be at least 600,000"):
        Settings(_env_file=None, **low_iter)

    # 3. Empty allowed_origins rejected in production
    no_origins = dict(base_prod)
    no_origins["secret_key"] = "R" * 32
    no_origins["allowed_origins"] = []
    with pytest.raises(ValueError, match="ALLOWED_ORIGINS must be configured"):
        Settings(_env_file=None, **no_origins)
