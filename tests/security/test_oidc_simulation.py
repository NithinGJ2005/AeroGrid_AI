"""Simulated OIDC / SSO single sign-on authentication and RBAC validation."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.auth.service import AuthenticationFailure, OIDCAuthenticator
from app.config import AuthMode, Environment, Settings
from app.main import create_app


@pytest.fixture(scope="module")
def rsa_key_pair():
    """Generate a dedicated 2048-bit RSA key pair for OIDC token signing."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture(scope="module")
def untrusted_key_pair():
    """Generate an untrusted RSA key pair for negative validation."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture
def oidc_settings(tmp_path):
    """Return Settings configured for OIDC authentication."""
    return Settings(
        app_name="AeroGrid AI OIDC Test",
        app_env=Environment.TEST,
        auth_mode=AuthMode.OIDC,
        oidc_issuer="https://sso.acme.internal/auth",
        oidc_jwks_url="https://sso.acme.internal/auth/jwks.json",
        auth_audience="enterprise-intranet-assistant",
        secret_key="test-secret-key-at-least-32-characters-long!",
        audit_log_path=str(tmp_path / "audit.jsonl"),
        enable_development_auth=False,
    )


def create_oidc_token(
    private_key,
    subject: str = "alex.rivera@acme.corp",
    roles: list[str] | None = None,
    issuer: str = "https://sso.acme.internal/auth",
    audience: str = "enterprise-intranet-assistant",
    expires_in_seconds: int = 3600,
    algorithm: str = "RS256",
) -> str:
    """Generate a signed OIDC JWT token."""
    now = int(time.time())
    claims = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "roles": roles if roles is not None else ["engineer", "employee"],
        "exp": now + expires_in_seconds,
        "iat": now,
    }
    return jwt.encode(claims, private_key, algorithm=algorithm, headers={"kid": "rsa-key-1"})


def test_oidc_valid_token_authentication(oidc_settings, rsa_key_pair):
    """Verify that a valid RS256-signed corporate OIDC token authenticates and maps permissions."""
    private_key, public_key = rsa_key_pair
    auth = OIDCAuthenticator(oidc_settings)

    mock_key = MagicMock()
    mock_key.key = public_key
    auth._jwks_client.get_signing_key_from_jwt = MagicMock(return_value=mock_key)

    token = create_oidc_token(
        private_key,
        subject="sarah.connor@acme.corp",
        roles=["engineer", "employee"],
    )

    identity = auth.authenticate(token)
    assert identity.subject == "sarah.connor@acme.corp"
    assert "engineer" in identity.roles
    assert "employee" in identity.roles
    assert "chat:use" in identity.permissions
    assert "engineering:read" in identity.permissions
    assert "database:read" in identity.permissions


def test_oidc_expired_token_rejected(oidc_settings, rsa_key_pair):
    """Verify that expired OIDC tokens are strictly rejected."""
    private_key, public_key = rsa_key_pair
    auth = OIDCAuthenticator(oidc_settings)

    mock_key = MagicMock()
    mock_key.key = public_key
    auth._jwks_client.get_signing_key_from_jwt = MagicMock(return_value=mock_key)

    expired_token = create_oidc_token(private_key, expires_in_seconds=-60)

    with pytest.raises(AuthenticationFailure, match="Invalid OIDC token"):
        auth.authenticate(expired_token)


def test_oidc_wrong_issuer_rejected(oidc_settings, rsa_key_pair):
    """Verify that tokens from an unauthorized IdP issuer are rejected."""
    private_key, public_key = rsa_key_pair
    auth = OIDCAuthenticator(oidc_settings)

    mock_key = MagicMock()
    mock_key.key = public_key
    auth._jwks_client.get_signing_key_from_jwt = MagicMock(return_value=mock_key)

    rogue_issuer_token = create_oidc_token(private_key, issuer="https://untrusted-idp.attacker.com")

    with pytest.raises(AuthenticationFailure, match="Invalid OIDC token"):
        auth.authenticate(rogue_issuer_token)


def test_oidc_wrong_audience_rejected(oidc_settings, rsa_key_pair):
    """Verify that tokens intended for other applications are rejected."""
    private_key, public_key = rsa_key_pair
    auth = OIDCAuthenticator(oidc_settings)

    mock_key = MagicMock()
    mock_key.key = public_key
    auth._jwks_client.get_signing_key_from_jwt = MagicMock(return_value=mock_key)

    wrong_aud_token = create_oidc_token(private_key, audience="different-corp-service")

    with pytest.raises(AuthenticationFailure, match="Invalid OIDC token"):
        auth.authenticate(wrong_aud_token)


def test_oidc_algorithm_confusion_rejected(oidc_settings):
    """Verify that symmetric algorithm confusion (e.g. HS256) is rejected."""
    auth = OIDCAuthenticator(oidc_settings)

    now = int(time.time())
    claims = {
        "iss": "https://sso.acme.internal/auth",
        "aud": "enterprise-intranet-assistant",
        "sub": "attacker@acme.corp",
        "roles": ["admin"],
        "exp": now + 3600,
        "iat": now,
    }
    hs256_token = jwt.encode(claims, "symmetric-key-attempt", algorithm="HS256")

    with pytest.raises(AuthenticationFailure, match="Invalid OIDC token"):
        auth.authenticate(hs256_token)


def test_oidc_untrusted_signature_rejected(oidc_settings, rsa_key_pair, untrusted_key_pair):
    """Verify that tokens signed by an untrusted RSA private key are rejected."""
    _, trusted_public_key = rsa_key_pair
    untrusted_private_key, _ = untrusted_key_pair

    auth = OIDCAuthenticator(oidc_settings)
    mock_key = MagicMock()
    mock_key.key = trusted_public_key
    auth._jwks_client.get_signing_key_from_jwt = MagicMock(return_value=mock_key)

    forged_token = create_oidc_token(untrusted_private_key)

    with pytest.raises(AuthenticationFailure, match="Invalid OIDC token"):
        auth.authenticate(forged_token)


def test_oidc_fastapi_endpoint_integration(oidc_settings, rsa_key_pair):
    """Verify end-to-end FastAPI endpoint behavior with OIDC bearer authentication and RBAC."""
    private_key, public_key = rsa_key_pair

    app = create_app(settings=oidc_settings)

    mock_key = MagicMock()
    mock_key.key = public_key
    app.state.authenticator._jwks_client.get_signing_key_from_jwt = MagicMock(return_value=mock_key)

    client = TestClient(app)

    # 1. Non-admin engineer OIDC token
    engineer_token = create_oidc_token(
        private_key,
        subject="dev.engineer@acme.corp",
        roles=["engineer", "employee"],
    )

    # Session / Identity check
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {engineer_token}"})
    assert resp.status_code == 200
    me = resp.json()
    assert me["subject"] == "dev.engineer@acme.corp"
    assert "engineer" in me["roles"]
    assert "engineering:read" in me["permissions"]

    # Negative RBAC check: non-admin hitting admin endpoint
    admin_resp = client.get("/api/v1/admin/audit-status", headers={"Authorization": f"Bearer {engineer_token}"})
    assert admin_resp.status_code == 403

    # 2. Administrative OIDC token
    admin_token = create_oidc_token(
        private_key,
        subject="sec.admin@acme.corp",
        roles=["admin"],
    )

    admin_resp_ok = client.get("/api/v1/admin/audit-status", headers={"Authorization": f"Bearer {admin_token}"})
    assert admin_resp_ok.status_code == 200
    assert admin_resp_ok.json()["status"] == "available"
    assert admin_resp_ok.json()["actor"] == "sec.admin@acme.corp"
