"""Comprehensive verification for durable SQLite auth, cookie-only browser sessions,
complete CSRF protection, PBKDF2 600k hashing upgrade, fine-grained administrative
permissions, role escalation defenses, and departmental isolation.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.auth.accounts import SqliteAuthStore, hash_password, verify_password
from app.config import Environment, Settings
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
        "password_hash_iterations": 100_000,  # Fast iterations for test speed
        "allowed_origins": ["http://127.0.0.1:8000", "http://localhost:8000"],
        "role_permission_map": {
            "employee": ["chat:use", "documents:search", "database:read"],
            "engineer": ["chat:use", "documents:search", "database:read", "engineering:read"],
            "hr": ["chat:use", "documents:search", "database:read", "hr:read"],
            "analyst": ["chat:use", "database:read"],
            "user_viewer": ["chat:use", "users:read"],
            "user_manager": ["chat:use", "users:read", "users:write"],
            "auditor": ["chat:use", "audit:read"],
            "operator": ["chat:use", "admin:diagnostics"],
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
# Priority 1: Durable Identity & Session State
# ---------------------------------------------------------------------------

def test_sqlite_durability_across_restarts(tmp_path: Path):
    """Verify accounts, deactivations, role changes, and revocations survive restarts."""
    db_file = tmp_path / "durable_auth.sqlite3"

    # Worker 1 / Process 1
    store1 = SqliteAuthStore(db_path=db_file, iterations=100_000)
    store1.create_user("charlie.parker", "ParkerPass2026!", "Charlie Parker", ["engineer"])
    store1.revoke("jti_test_revocation_123", subject="charlie.parker", expires_at=time.time() + 3600)
    store1.set_active_status("alice.chen", False)
    store1.update_roles("bob.smith", ["engineer", "hr"])

    # Simulate restart: open new store instance on same file
    store2 = SqliteAuthStore(db_path=db_file, iterations=100_000)

    # 1. New user survived
    charlie = store2.get_user("charlie.parker")
    assert charlie is not None
    assert charlie.full_name == "Charlie Parker"
    assert charlie.roles == ["engineer"]

    # 2. Deactivation survived
    alice = store2.get_user("alice.chen")
    assert alice is not None
    assert alice.is_active is False
    assert store2.authenticate("alice.chen", "EngineeringLead2026!") is None

    # 3. Role change survived
    bob = store2.get_user("bob.smith")
    assert bob is not None
    assert set(bob.roles) == {"engineer", "hr"}

    # 4. Revocation survived
    assert store2.is_revoked("jti_test_revocation_123") is True


def test_sqlite_backup_and_recovery(tmp_path: Path):
    """Verify online hot backup creates an exact, queryable snapshot."""
    db_file = tmp_path / "primary_auth.sqlite3"
    backup_file = tmp_path / "backup_auth.sqlite3"

    store = SqliteAuthStore(db_path=db_file, iterations=100_000)
    store.create_user("diana.prince", "DianaAmazon2026!", "Diana Prince", ["admin"])
    store.revoke("jti_backup_check", subject="diana.prince", expires_at=time.time() + 3600)

    # Perform online hot backup
    store.backup(backup_file)
    assert backup_file.is_file()

    # Recover from backup
    recovered_store = SqliteAuthStore(db_path=backup_file, iterations=100_000)
    diana = recovered_store.get_user("diana.prince")
    assert diana is not None
    assert diana.full_name == "Diana Prince"
    assert recovered_store.is_revoked("jti_backup_check") is True


def test_sqlite_prune_expired_revocations(tmp_path: Path):
    """Verify expired session revocations are pruned while active ones are preserved."""
    store = SqliteAuthStore(db_path=":memory:", iterations=100_000)
    now = time.time()

    # Expired 1 hour ago
    store.revoke("jti_expired", expires_at=now - 3600)
    # Active for 1 more hour
    store.revoke("jti_active", expires_at=now + 3600)

    deleted = store.prune_expired()
    assert deleted == 1
    assert store.is_revoked("jti_expired") is False
    assert store.is_revoked("jti_active") is True


# ---------------------------------------------------------------------------
# Priority 2: Cookie-Only Browser Authentication
# ---------------------------------------------------------------------------

def test_browser_login_cookie_only_no_bearer_token():
    """Verify browser logins receive NO bearer token in JSON, but receive session and CSRF cookies."""
    cfg = make_test_settings()
    app = create_app(cfg)
    client = TestClient(app)

    res = client.post(
        "/api/v1/auth/login",
        json={"username": "alice.chen", "password": "EngineeringLead2026!", "client_type": "browser"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["access_token"] is None
    assert data["token_type"] is None
    assert data["csrf_token"] != ""
    assert data["user"]["username"] == "alice.chen"

    # Cookies must be set
    assert "assistant_session" in res.cookies
    assert "assistant_csrf" in res.cookies

    # Browser automatically authenticates subsequent requests via cookie only
    me_res = client.get("/api/v1/auth/me")
    assert me_res.status_code == 200
    assert me_res.json()["subject"] == "alice.chen"


def test_api_client_token_endpoint_returns_bearer_token():
    """Verify programmatic API client endpoint returns a bearer token for non-browser automation."""
    cfg = make_test_settings()
    app = create_app(cfg)
    client = TestClient(app)

    res = client.post(
        "/api/v1/auth/token",
        json={"username": "bob.smith", "password": "StaffEngineer2026!"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["access_token"] is not None
    assert data["token_type"] == "bearer"

    # API client uses Authorization: Bearer
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    me_res = client.get("/api/v1/auth/me", headers=headers)
    assert me_res.status_code == 200
    assert me_res.json()["subject"] == "bob.smith"


# ---------------------------------------------------------------------------
# Priority 3: Complete CSRF Protection
# ---------------------------------------------------------------------------

def test_csrf_cookie_mutations_protection():
    """Verify all CSRF edge cases for cookie-authenticated mutating requests."""
    cfg = make_test_settings()
    app = create_app(cfg)
    client = TestClient(app)

    # Browser login establishes session and CSRF cookies
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "bob.smith", "password": "StaffEngineer2026!", "client_type": "browser"},
    )
    csrf_token = login_res.json()["csrf_token"]

    # 1. Cross-site Sec-Fetch-Site blocked (403)
    res_cross = client.post(
        "/api/v1/auth/logout",
        headers={"sec-fetch-site": "cross-site", "origin": "http://127.0.0.1:8000", "x-csrf-token": csrf_token},
    )
    assert res_cross.status_code == 403
    assert "cross-site fetch blocked" in res_cross.json()["message"]

    # 2. Untrusted Origin blocked (403)
    res_evil_orig = client.post(
        "/api/v1/auth/logout",
        headers={"origin": "http://evil-phishing.com", "x-csrf-token": csrf_token},
    )
    assert res_evil_orig.status_code == 403
    assert "untrusted origin" in res_evil_orig.json()["message"]

    # 3. Untrusted Referer blocked (403)
    res_evil_ref = client.post(
        "/api/v1/auth/logout",
        headers={"referer": "http://evil-phishing.com/attack.html", "x-csrf-token": csrf_token},
    )
    assert res_evil_ref.status_code == 403
    assert "untrusted origin" in res_evil_ref.json()["message"]

    # 4. Missing anti-CSRF token header blocked (403)
    res_no_csrf = client.post(
        "/api/v1/auth/logout",
        headers={"origin": "http://127.0.0.1:8000"},
    )
    assert res_no_csrf.status_code == 403
    assert "missing or invalid anti-CSRF token" in res_no_csrf.json()["message"]

    # 5. Invalid/forged anti-CSRF token header blocked (403)
    res_bad_csrf = client.post(
        "/api/v1/auth/logout",
        headers={"origin": "http://127.0.0.1:8000", "x-csrf-token": "forged_csrf_token_123"},
    )
    assert res_bad_csrf.status_code == 403
    assert "missing or invalid anti-CSRF token" in res_bad_csrf.json()["message"]

    # 6. Legitimate same-origin request with matching CSRF token succeeds (200)
    res_good = client.post(
        "/api/v1/auth/logout",
        headers={"origin": "http://127.0.0.1:8000", "x-csrf-token": csrf_token},
    )
    assert res_good.status_code == 200
    assert res_good.json()["status"] == "logged_out"


def test_csrf_bearer_token_api_bypasses_cookie_csrf():
    """Verify programmatic API calls using Authorization: Bearer bypass ambient cookie CSRF checks."""
    cfg = make_test_settings()
    app = create_app(cfg)
    client = TestClient(app)

    token_res = client.post(
        "/api/v1/auth/token",
        json={"username": "bob.smith", "password": "StaffEngineer2026!"},
    )
    bearer = token_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {bearer}"}

    # Calling mutating endpoint without Origin or CSRF token succeeds because it uses Bearer token
    logout_res = client.post("/api/v1/auth/logout", headers=headers)
    assert logout_res.status_code == 200


# ---------------------------------------------------------------------------
# Priority 4: Password Hashing Parameters & Upgrade Migration
# ---------------------------------------------------------------------------

def test_password_hash_automatic_migration(tmp_path: Path):
    """Verify legacy 100k hashes automatically upgrade to 600k on successful login."""
    db_file = tmp_path / "migration_test.sqlite3"

    # Step 1: Create store configured with legacy 100k iterations
    legacy_store = SqliteAuthStore(db_path=db_file, iterations=100_000)
    legacy_store.create_user("legacy.user", "LegacySecret2026!", "Legacy User", ["employee"])

    acc_before = legacy_store.get_user("legacy.user")
    assert acc_before.iterations == 100_000
    old_hash = acc_before.password_hash

    # Step 2: Open store configured with target 600k iterations
    upgraded_store = SqliteAuthStore(db_path=db_file, iterations=600_000)

    # Step 3: User logs in -> verify password succeeds and hash is upgraded
    authenticated = upgraded_store.authenticate("legacy.user", "LegacySecret2026!")
    assert authenticated is not None
    assert authenticated.iterations == 600_000
    assert authenticated.password_hash != old_hash

    # Step 4: Verify upgrade persisted in database
    acc_after = upgraded_store.get_user("legacy.user")
    assert acc_after.iterations == 600_000

    # Step 5: Check admin audit event for migration
    audit_events = upgraded_store.list_admin_audit_events()
    assert any(e["action"] == "password_hash_migrated" for e in audit_events)


def test_admin_password_reset_and_session_invalidation():
    """Verify admin password reset revokes all existing sessions for the target user."""
    cfg = make_test_settings()
    app = create_app(cfg)
    client = TestClient(app)

    # Bob logs in and gets an active token
    bob_login = client.post(
        "/api/v1/auth/token",
        json={"username": "bob.smith", "password": "StaffEngineer2026!"},
    )
    bob_headers = {"Authorization": f"Bearer {bob_login.json()['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=bob_headers).status_code == 200

    # Admin logs in
    admin_login = client.post(
        "/api/v1/auth/token",
        json={"username": "admin.system", "password": "AdminSecurity2026!"},
    )
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

    # Admin resets Bob's password
    reset_res = client.post(
        "/api/v1/admin/users/bob.smith/reset-password",
        headers=admin_headers,
        json={"new_password": "NewStaffPass2026!"},
    )
    assert reset_res.status_code == 200
    assert reset_res.json()["status"] == "password_reset"

    # Bob's previous token is now revoked
    assert client.get("/api/v1/auth/me", headers=bob_headers).status_code == 401

    # Bob logs in with old password -> fails
    old_login = client.post(
        "/api/v1/auth/token",
        json={"username": "bob.smith", "password": "StaffEngineer2026!"},
    )
    assert old_login.status_code == 401

    # Bob logs in with new password -> succeeds
    new_login = client.post(
        "/api/v1/auth/token",
        json={"username": "bob.smith", "password": "NewStaffPass2026!"},
    )
    assert new_login.status_code == 200
    new_headers = {"Authorization": f"Bearer {new_login.json()['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=new_headers).status_code == 200


def test_production_mode_does_not_seed_demo_accounts():
    """Verify that in production mode, demo accounts with default passwords are not seeded."""
    store = SqliteAuthStore(db_path=":memory:", is_production=True)
    users = store.list_users()
    assert len(users) == 0
    assert store.get_user("alice.chen") is None
    assert store.get_user("admin.system") is None


# ---------------------------------------------------------------------------
# Priority 5: Fine-Grained Administrative Authorization
# ---------------------------------------------------------------------------

def test_fine_grained_administrative_permissions():
    """Verify distinct separation of users:read, users:write, audit:read, and admin:diagnostics."""
    cfg = make_test_settings()
    app = create_app(cfg)
    client = TestClient(app)

    # 1. Admin provisions specific roles
    admin_login = client.post(
        "/api/v1/auth/token",
        json={"username": "admin.system", "password": "AdminSecurity2026!"},
    )
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

    client.post(
        "/api/v1/admin/users",
        headers=admin_headers,
        json={"username": "reader.user", "password": "ReaderPass2026!", "full_name": "Reader", "roles": ["user_viewer"]},
    )
    client.post(
        "/api/v1/admin/users",
        headers=admin_headers,
        json={"username": "manager.user", "password": "ManagerPass2026!", "full_name": "Manager", "roles": ["user_manager"]},
    )
    client.post(
        "/api/v1/admin/users",
        headers=admin_headers,
        json={"username": "auditor.user", "password": "AuditorPass2026!", "full_name": "Auditor", "roles": ["auditor"]},
    )

    # 2. Reader (users:read only)
    reader_login = client.post("/api/v1/auth/token", json={"username": "reader.user", "password": "ReaderPass2026!"})
    reader_h = {"Authorization": f"Bearer {reader_login.json()['access_token']}"}
    assert client.get("/api/v1/admin/users", headers=reader_h).status_code == 200
    assert client.post("/api/v1/admin/users", headers=reader_h, json={"username": "x", "password": "x", "full_name": "x"}).status_code == 403
    assert client.get("/api/v1/admin/audit-events", headers=reader_h).status_code == 403
    assert client.get("/api/v1/admin/metrics", headers=reader_h).status_code == 403

    # 3. Manager (users:read, users:write)
    mgr_login = client.post("/api/v1/auth/token", json={"username": "manager.user", "password": "ManagerPass2026!"})
    mgr_h = {"Authorization": f"Bearer {mgr_login.json()['access_token']}"}
    assert client.get("/api/v1/admin/users", headers=mgr_h).status_code == 200
    assert client.get("/api/v1/admin/audit-events", headers=mgr_h).status_code == 403
    assert client.get("/api/v1/admin/metrics", headers=mgr_h).status_code == 403

    # 4. Auditor (audit:read only)
    auditor_login = client.post("/api/v1/auth/token", json={"username": "auditor.user", "password": "AuditorPass2026!"})
    aud_h = {"Authorization": f"Bearer {auditor_login.json()['access_token']}"}
    assert client.get("/api/v1/admin/audit-events", headers=aud_h).status_code == 200
    assert client.get("/api/v1/admin/users", headers=aud_h).status_code == 403
    assert client.get("/api/v1/admin/metrics", headers=aud_h).status_code == 403


def test_self_assignment_and_privilege_escalation_defenses():
    """Verify users cannot self-escalate roles or grant admin roles beyond their authority."""
    cfg = make_test_settings()
    app = create_app(cfg)
    client = TestClient(app)

    admin_login = client.post(
        "/api/v1/auth/token",
        json={"username": "admin.system", "password": "AdminSecurity2026!"},
    )
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

    # Provision user_manager who has users:write but NOT admin role
    client.post(
        "/api/v1/admin/users",
        headers=admin_headers,
        json={"username": "manager.user", "password": "ManagerPass2026!", "full_name": "Manager", "roles": ["user_manager"]},
    )

    mgr_login = client.post("/api/v1/auth/token", json={"username": "manager.user", "password": "ManagerPass2026!"})
    mgr_h = {"Authorization": f"Bearer {mgr_login.json()['access_token']}"}

    # 1. Manager tries to edit their own roles (self-escalation) -> 403 Forbidden
    self_esc = client.patch(
        "/api/v1/admin/users/manager.user",
        headers=mgr_h,
        json={"roles": ["admin"]},
    )
    assert self_esc.status_code == 403
    assert "Self-assignment of roles is strictly prohibited" in self_esc.json()["message"]

    # 2. Non-admin manager tries to grant admin role to someone else -> 403 Forbidden
    grant_admin = client.post(
        "/api/v1/admin/users",
        headers=mgr_h,
        json={"username": "new.admin", "password": "NewAdminPass2026!", "full_name": "New Admin", "roles": ["admin"]},
    )
    assert grant_admin.status_code == 403
    assert "Cannot grant admin role" in grant_admin.json()["message"]

    # 3. Manager tries to deactivate their own account -> 403 Forbidden
    self_deact = client.patch(
        "/api/v1/admin/users/manager.user",
        headers=mgr_h,
        json={"is_active": False},
    )
    assert self_deact.status_code == 403


# ---------------------------------------------------------------------------
# Priority 6: Data Isolation & Direct MCP Execution
# ---------------------------------------------------------------------------

def test_direct_mcp_call_authorization_and_isolation():
    """Verify direct MCP tool executions enforce authorization boundaries independently."""
    cfg = make_test_settings()
    app = create_app(cfg)
    client = TestClient(app)

    # Engineer
    eng_login = client.post("/api/v1/auth/token", json={"username": "alice.chen", "password": "EngineeringLead2026!"})
    eng_h = {"Authorization": f"Bearer {eng_login.json()['access_token']}"}

    # HR
    hr_login = client.post("/api/v1/auth/token", json={"username": "david.miller", "password": "HRPartner2026!"})
    hr_h = {"Authorization": f"Bearer {hr_login.json()['access_token']}"}

    # Direct DB MCP call: Engineer accessing HR records -> 403 Forbidden
    eng_on_hr_db = client.post(
        "/api/v1/mcp/tools/query_database",
        headers=eng_h,
        json={"parameters": {"query_id": "hr.employee_records"}},
    )
    assert eng_on_hr_db.status_code == 403

    # Direct DB MCP call: HR accessing Engineering inventory -> 403 Forbidden
    hr_on_eng_db = client.post(
        "/api/v1/mcp/tools/query_database",
        headers=hr_h,
        json={"parameters": {"query_id": "engineering.system_inventory"}},
    )
    assert hr_on_eng_db.status_code == 403

    # Direct Doc MCP call: Engineer searching HR topics gets 0 citations
    eng_on_hr_docs = client.post(
        "/api/v1/mcp/tools/search_documents",
        headers=eng_h,
        json={"parameters": {"query": "Salary Banding 401(k)"}},
    )
    assert eng_on_hr_docs.status_code == 200
    assert len(eng_on_hr_docs.json()["citations"]) == 0

    # Direct Doc MCP call: HR searching Eng topics gets 0 citations
    hr_on_eng_docs = client.post(
        "/api/v1/mcp/tools/search_documents",
        headers=hr_h,
        json={"parameters": {"query": "Kubernetes branching deployment"}},
    )
    assert hr_on_eng_docs.status_code == 200
    assert len(hr_on_eng_docs.json()["citations"]) == 0


def test_role_changes_immediately_invalidate_permissions():
    """Verify modifying a user's roles immediately updates authorization without token reissue or restart."""
    cfg = make_test_settings()
    app = create_app(cfg)
    client = TestClient(app)

    # Admin logs in
    admin_login = client.post("/api/v1/auth/token", json={"username": "admin.system", "password": "AdminSecurity2026!"})
    admin_h = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

    # David Miller logs in with 'hr' role
    hr_login = client.post("/api/v1/auth/token", json={"username": "david.miller", "password": "HRPartner2026!"})
    hr_h = {"Authorization": f"Bearer {hr_login.json()['access_token']}"}

    # Initially, David can query HR employee records
    res_before = client.post(
        "/api/v1/mcp/tools/query_database",
        headers=hr_h,
        json={"parameters": {"query_id": "hr.employee_records"}},
    )
    assert res_before.status_code == 200

    # Admin strips 'hr' role from David, reducing him to 'employee'
    patch_res = client.patch(
        "/api/v1/admin/users/david.miller",
        headers=admin_h,
        json={"roles": ["employee"]},
    )
    assert patch_res.status_code == 200

    # With the SAME existing token, David is now IMMEDIATELY DENIED access to HR records
    res_after = client.post(
        "/api/v1/mcp/tools/query_database",
        headers=hr_h,
        json={"parameters": {"query_id": "hr.employee_records"}},
    )
    assert res_after.status_code == 403

    # Admin restores 'hr' role to David
    patch_res2 = client.patch(
        "/api/v1/admin/users/david.miller",
        headers=admin_h,
        json={"roles": ["hr"]},
    )
    assert patch_res2.status_code == 200

    # With the same existing token, David is IMMEDIATELY RE-AUTHORIZED
    res_restored = client.post(
        "/api/v1/mcp/tools/query_database",
        headers=hr_h,
        json={"parameters": {"query_id": "hr.employee_records"}},
    )
    assert res_restored.status_code == 200


def test_document_cache_invalidation_on_acl_change(tmp_path: Path):
    """Verify document chunk cache is invalidated when adjacent ACL changes."""
    from app.documents.service import DocumentIndexer
    from app.auth.service import Identity

    doc_path = tmp_path / "benefits_guide.txt"
    doc_path.write_text("Confidential Executive Healthcare and 401(k) Match policy.", encoding="utf-8")
    acl_path = tmp_path / "benefits_guide.txt.acl.json"
    acl_path.write_text(json.dumps({"allowed_roles": ["hr"]}), encoding="utf-8")

    indexer = DocumentIndexer([tmp_path], chunk_size=200, chunk_overlap=20)
    rep1 = indexer.reindex()
    assert rep1.indexed_documents == 1
    assert rep1.reused_documents == 0

    # Second index with identical content and ACL -> chunks reused from cache
    rep2 = indexer.reindex()
    assert rep2.indexed_documents == 0
    assert rep2.reused_documents == 1

    # HR identity can search and find chunks
    hr_identity = Identity("david.miller", frozenset(["hr"]), frozenset(["documents:search"]))
    results = indexer.search("Healthcare", hr_identity)
    assert len(results) == 1
    assert results[0].citation.filename == "benefits_guide.txt"

    # Now change the ACL to admin only: cache MUST be invalidated even though file content is unchanged
    acl_path.write_text(json.dumps({"allowed_roles": ["admin"]}), encoding="utf-8")
    rep3 = indexer.reindex()
    assert rep3.indexed_documents == 1  # Re-indexed because content_hash (content + acl) changed!
    assert rep3.reused_documents == 0

    # HR identity now gets 0 chunks (immediate retrieval denial)
    results_hr = indexer.search("Healthcare", hr_identity)
    assert len(results_hr) == 0

    # Admin identity gets the chunk
    admin_identity = Identity("admin.system", frozenset(["admin"]), frozenset(["documents:search"]))
    results_admin = indexer.search("Healthcare", admin_identity)
    assert len(results_admin) == 1


def test_cross_user_conversation_and_context_isolation():
    """Verify multi-user queries maintain strict state, citation, and context isolation."""
    from app.audit import InMemoryAuditSink
    from app.llm.service import GenerationResult, LocalLLMClient
    from app.orchestration.mcp import MCPToolRegistry
    from app.orchestration.service import IntranetAssistantService
    from app.auth.service import Identity

    class EchoLLM(LocalLLMClient):
        def __init__(self):
            pass
        def generate(self, messages, max_tokens=None, temperature=None):
            last_msg = messages[-1].content
            return GenerationResult(content=f"Echo: {last_msg}", model="mock-model", prompt_tokens=5, completion_tokens=5)

    audit_sink = InMemoryAuditSink()
    registry = MCPToolRegistry(audit_sink)
    cfg = make_test_settings()
    assistant = IntranetAssistantService(cfg, EchoLLM(), registry, audit_sink)

    alice = Identity("alice.chen", frozenset(["engineer"]), frozenset(["chat:use"]))
    david = Identity("david.miller", frozenset(["hr"]), frozenset(["chat:use"]))

    # Alice asks a proprietary engineering question
    res_alice = assistant.ask("What is our production Kubernetes cluster configuration?", alice, "req-1")
    assert "Kubernetes" in res_alice.response

    # David asks an HR question in a distinct session
    res_david = assistant.ask("What are the standard maternity leave allowances?", david, "req-2")
    assert "maternity leave" in res_david.response
    assert "Kubernetes" not in res_david.response

