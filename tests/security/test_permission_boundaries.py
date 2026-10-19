"""Security Verification: Role and Permission Boundary Defenses."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest

from app.audit import InMemoryAuditSink
from app.auth.service import AuthenticationFailure, DevelopmentTokenAuthenticator, Identity
from app.config import Settings
from app.documents.service import DocumentIndexer
from app.orchestration.mcp import (
    DocumentSearchMCPTool,
    MCPAuthorizationError,
)


def make_settings(**overrides) -> Settings:
    values = {
        "app_env": "test",
        "secret_key": "x" * 32,
        "dev_auth_signing_key": "k" * 32,
        "enable_development_auth": True,
        "role_permission_map": {
            "employee": ["chat:use", "documents:search"],
            "analyst": ["chat:use", "database:read"],
            "executive": ["chat:use", "documents:search", "database:read", "admin:diagnostics"],
        },
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_tampered_token_signature_rejected():
    """Verify forged JWT signatures are rejected without granting access."""
    cfg = make_settings()
    auth = DevelopmentTokenAuthenticator(cfg)

    # Valid token signed with correct key
    valid_token = jwt.encode(
        {"sub": "attacker", "roles": ["executive"], "aud": cfg.auth_audience, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        cfg.dev_auth_signing_key.get_secret_value(),
        algorithm="HS256",
    )

    # Token signed with a forged attacker key
    forged_token = jwt.encode(
        {"sub": "attacker", "roles": ["executive"], "aud": cfg.auth_audience, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        "wrong_attacker_secret_key_at_least_32_characters_long",
        algorithm="HS256",
    )

    # Valid token succeeds
    identity = auth.authenticate(valid_token)
    assert identity.subject == "attacker"

    # Forged token fails
    with pytest.raises(AuthenticationFailure):
        auth.authenticate(forged_token)


def test_deny_by_default_role_permission_mapping():
    """Verify unmapped or unknown roles obtain zero permissions."""
    cfg = make_settings(role_permission_map={})  # Empty mapping
    auth = DevelopmentTokenAuthenticator(cfg)

    token = jwt.encode(
        {"sub": "employee-1", "roles": ["admin", "superuser", "root"], "aud": cfg.auth_audience, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        cfg.dev_auth_signing_key.get_secret_value(),
        algorithm="HS256",
    )

    identity = auth.authenticate(token)
    # Even though user claims "admin" and "superuser", server map is empty -> 0 permissions
    assert len(identity.permissions) == 0


def test_document_acl_cross_role_isolation(tmp_path: Path):
    """Verify users cannot access documents restricted to other roles."""
    exec_doc = tmp_path / "executive_compensation.txt"
    exec_doc.write_text("Executive bonus and stock option allocations.", encoding="utf-8")
    exec_doc.with_suffix(".txt.acl.json").write_text(
        json.dumps({"allowed_roles": ["executive"]}), encoding="utf-8"
    )

    indexer = DocumentIndexer([tmp_path], 100, 10)
    indexer.reindex()

    # Regular employee with documents:search permission, but role "employee"
    employee_identity = Identity("regular-emp", frozenset({"employee"}), frozenset({"documents:search"}))
    results = indexer.search("bonus", employee_identity)
    assert len(results) == 0

    # Executive identity with role "executive"
    exec_identity = Identity("ceo", frozenset({"executive"}), frozenset({"documents:search"}))
    exec_results = indexer.search("bonus", exec_identity)
    assert len(exec_results) == 1
    assert "bonus" in exec_results[0].content


def test_missing_or_malformed_acl_denies_access_by_default(tmp_path: Path):
    """Verify documents lacking valid ACL files are unreachable by any user."""
    unprotected_doc = tmp_path / "secret.txt"
    unprotected_doc.write_text("Unclassified confidential text", encoding="utf-8")
    # Intentionally omit .acl.json file

    indexer = DocumentIndexer([tmp_path], 100, 10)
    indexer.reindex()

    exec_identity = Identity("ceo", frozenset({"executive"}), frozenset({"documents:search"}))
    results = indexer.search("confidential", exec_identity)
    assert len(results) == 0


def test_engineer_hr_mutual_document_isolation():
    """Verify Engineer cannot access HR documents, and HR cannot access Engineering documents."""
    sample_docs_path = Path("sample_docs")
    indexer = DocumentIndexer([sample_docs_path], 800, 120)
    indexer.reindex()

    engineer_identity = Identity(
        subject="alice.dev",
        roles=frozenset({"engineer"}),
        permissions=frozenset({"chat:use", "documents:search", "engineering:read"}),
    )
    hr_identity = Identity(
        subject="bob.hr",
        roles=frozenset({"hr"}),
        permissions=frozenset({"chat:use", "documents:search", "hr:read"}),
    )

    # Engineer searches for engineering handbook -> found
    eng_results = indexer.search("branching strategy", engineer_identity)
    assert len(eng_results) > 0
    assert any("engineering_handbook.md" == r.citation.filename for r in eng_results)

    # Engineer searches for HR compensation guide -> denied / empty
    hr_results_for_eng = indexer.search("salary band", engineer_identity)
    assert len(hr_results_for_eng) == 0

    # HR searches for HR compensation guide -> found
    hr_results = indexer.search("salary band", hr_identity)
    assert len(hr_results) > 0
    assert any("hr_benefits_guide.md" == r.citation.filename for r in hr_results)

    # HR searches for engineering handbook -> denied / empty
    eng_results_for_hr = indexer.search("branching strategy", hr_identity)
    assert len(eng_results_for_hr) == 0


def test_mcp_tools_filtered_by_caller_permissions():
    """Verify that MCP tool descriptors are dynamically filtered based on caller permissions."""
    from app.orchestration.mcp import MCPToolRegistry

    registry = MCPToolRegistry(InMemoryAuditSink())
    # Create mock tool requiring database:read
    class DummyDocTool:
        name = "search_documents"
        required_permission = "documents:search"
        def get_descriptor(self):
            return {"name": self.name, "required_permission": self.required_permission}

    class DummyDbTool:
        name = "query_database"
        required_permission = "database:read"
        def get_descriptor(self):
            return {"name": self.name, "required_permission": self.required_permission}

    registry.register(DummyDocTool())
    registry.register(DummyDbTool())

    # User with only documents:search sees only search_documents
    doc_only_identity = Identity("user1", frozenset({"employee"}), frozenset({"documents:search"}))
    descriptors = registry.list_descriptors_for_identity(doc_only_identity)
    assert len(descriptors) == 1
    assert descriptors[0]["name"] == "search_documents"

    # Admin with both permissions sees both tools
    admin_identity = Identity("admin1", frozenset({"admin"}), frozenset({"documents:search", "database:read"}))
    admin_descriptors = registry.list_descriptors_for_identity(admin_identity)
    assert len(admin_descriptors) == 2


def test_auth_me_endpoint_returns_identity_and_roles():
    """Verify GET /api/v1/auth/me returns subject, roles, and mapped permissions."""
    from starlette.testclient import TestClient
    from app.main import create_app

    cfg = make_settings()
    app = create_app(cfg)
    client = TestClient(app)

    auth = DevelopmentTokenAuthenticator(cfg)
    tok = jwt.encode(
        {"sub": "charlie@company.internal", "roles": ["employee"], "aud": cfg.auth_audience, "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        cfg.dev_auth_signing_key.get_secret_value(),
        algorithm="HS256",
    )

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert response.status_code == 200
    data = response.json()
    assert data["subject"] == "charlie@company.internal"
    assert data["roles"] == ["employee"]
    assert "chat:use" in data["permissions"]
