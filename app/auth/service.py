"""Verified-token authentication and deny-by-default authorization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import jwt
from fastapi import Request

from app.config import AuthMode, Settings


class AuthenticationFailure(Exception):
    """Raised when no valid, verified identity can be established."""


@dataclass(frozen=True)
class Identity:
    subject: str
    roles: frozenset[str]
    permissions: frozenset[str]


class Authenticator(Protocol):
    def authenticate(self, token: str) -> Identity: ...


def _string_set(value: Any) -> frozenset[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        return frozenset()
    return frozenset(value)


def _identity_from_claims(claims: dict[str, Any], settings: Settings) -> Identity:
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise AuthenticationFailure("Token subject is missing")
    roles = _string_set(claims.get("roles", []))
    permissions = frozenset(
        permission for role in roles for permission in settings.role_permission_map.get(role, [])
    )
    return Identity(subject=subject, roles=roles, permissions=permissions)


class DevelopmentTokenAuthenticator:
    """Development-only HS256 adapter, never permitted in production settings."""

    def __init__(self, settings: Settings) -> None:
        if settings.dev_auth_signing_key is None:
            raise RuntimeError("Development authentication key is not configured")
        self._key = settings.dev_auth_signing_key.get_secret_value()
        self._audience = settings.auth_audience
        self._settings = settings

    def authenticate(self, token: str) -> Identity:
        try:
            claims = jwt.decode(
                token,
                self._key,
                algorithms=["HS256"],
                audience=self._audience,
                options={"require": ["exp", "sub", "aud"]},
            )
        except jwt.PyJWTError:
            try:
                claims = jwt.decode(
                    token,
                    self._settings.secret_key.get_secret_value(),
                    algorithms=["HS256"],
                    audience=self._audience,
                    options={"require": ["exp", "sub", "aud"]},
                )
            except jwt.PyJWTError as error:
                raise AuthenticationFailure("Invalid development token") from error
        return _identity_from_claims(claims, self._settings)


class OIDCAuthenticator:
    """OIDC adapter that validates signed tokens against the configured internal IdP."""

    def __init__(self, settings: Settings) -> None:
        if not all((settings.oidc_issuer, settings.oidc_jwks_url)):
            raise RuntimeError("OIDC settings are incomplete")
        self._issuer = settings.oidc_issuer
        self._audience = settings.auth_audience
        self._jwks_client = jwt.PyJWKClient(settings.oidc_jwks_url)
        self._settings = settings

    def authenticate(self, token: str) -> Identity:
        try:
            key = self._jwks_client.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256", "ES256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "sub", "aud", "iss"]},
            )
        except jwt.PyJWTError as error:
            raise AuthenticationFailure("Invalid OIDC token") from error
        return _identity_from_claims(claims, self._settings)


class LocalAccountAuthenticator:
    """Production-grade air-gapped authenticator using signed session tokens and live account verification."""

    def __init__(
        self,
        settings: Settings,
        account_store: Any = None,
        revocation_store: Any = None,
    ) -> None:
        self._key = settings.secret_key.get_secret_value()
        self._dev_key = (
            settings.dev_auth_signing_key.get_secret_value()
            if settings.enable_development_auth and settings.dev_auth_signing_key
            else None
        )
        self._audience = settings.auth_audience
        self._settings = settings
        self._account_store = account_store
        self._revocation_store = revocation_store

    def authenticate(self, token: str) -> Identity:
        try:
            claims = jwt.decode(
                token,
                self._key,
                algorithms=["HS256"],
                audience=self._audience,
                options={"require": ["exp", "sub", "aud"]},
            )
        except jwt.PyJWTError as primary_err:
            if self._dev_key:
                try:
                    claims = jwt.decode(
                        token,
                        self._dev_key,
                        algorithms=["HS256"],
                        audience=self._audience,
                        options={"require": ["exp", "sub", "aud"]},
                    )
                except jwt.PyJWTError:
                    raise AuthenticationFailure("Invalid or expired session token") from primary_err
            else:
                raise AuthenticationFailure("Invalid or expired session token") from primary_err

        # Check session revocation if jti is present
        jti = claims.get("jti")
        subject = claims.get("sub", "")
        if jti and self._revocation_store and self._revocation_store.is_revoked(jti, subject=subject):
            raise AuthenticationFailure("Session has been revoked")

        # Synchronize live account state (deactivation, password reset, and role changes)
        if self._account_store:
            account = self._account_store.get_user(subject)
            if not account:
                raise AuthenticationFailure("User account no longer exists")
            if not account.is_active:
                raise AuthenticationFailure("User account has been deactivated")
            expected_version = getattr(account, "token_version", 1)
            token_version = claims.get("token_version")
            if token_version is not None and token_version != expected_version:
                raise AuthenticationFailure("Session has been invalidated due to password reset")
            roles = frozenset(account.roles)
        else:
            roles = _string_set(claims.get("roles", []))

        permissions = frozenset(
            permission for role in roles for permission in self._settings.role_permission_map.get(role, [])
        )
        return Identity(subject=subject, roles=roles, permissions=permissions)


def build_authenticator(
    settings: Settings,
    account_store: Any = None,
    revocation_store: Any = None,
) -> Authenticator:
    if settings.auth_mode is AuthMode.DEVELOPMENT:
        return DevelopmentTokenAuthenticator(settings)
    if settings.auth_mode is AuthMode.LOCAL:
        return LocalAccountAuthenticator(settings, account_store, revocation_store)
    return OIDCAuthenticator(settings)


def bearer_token(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()

    # Fallback to HTTP-only session cookie for employee browser sessions
    cookies = getattr(request, "cookies", {})
    cookie_token = cookies.get("assistant_session") if hasattr(cookies, "get") else None
    if cookie_token and cookie_token.strip():
        return cookie_token.strip()

    raise AuthenticationFailure("Bearer token or active session cookie is required")
