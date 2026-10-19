"""FastAPI dependencies that enforce identity, permissions, and CSRF protection on the server."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from urllib.parse import urlsplit

from fastapi import Request

from app.audit import AuditSink, new_event
from app.auth.service import AuthenticationFailure, Identity, bearer_token
from app.config import Environment


class AuthorizationFailure(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(message)


def validate_csrf(request: Request) -> None:
    """Validate CSRF protection for cookie-authenticated state-changing requests."""
    headers = getattr(request, "headers", {})
    method = getattr(request, "method", "GET").upper()
    if method not in {"POST", "PUT", "DELETE", "PATCH"}:
        return

    # Skip CSRF check for credential login and token endpoints
    if request.url.path.endswith("/auth/login") or request.url.path.endswith("/auth/token"):
        return

    # API clients using explicit Bearer tokens are immune to ambient cookie CSRF
    auth_header = headers.get("authorization") or headers.get("Authorization")
    if auth_header and auth_header.strip().lower().startswith("bearer "):
        return

    cookies = getattr(request, "cookies", {})
    session_cookie = cookies.get("assistant_session")
    if not session_cookie:
        # Request does not use ambient session cookie; unauthenticated requests fail in auth
        return

    settings = getattr(request.app.state, "settings", None)
    request_id = getattr(request.state, "request_id", "unknown")

    # 1. Sec-Fetch-Site check
    sec_fetch_site = headers.get("sec-fetch-site")
    if sec_fetch_site and sec_fetch_site.lower() == "cross-site":
        if hasattr(request.app.state, "audit_sink"):
            request.app.state.audit_sink.record(
                new_event("csrf_protection", "denied", request_id, resource=request.url.path)
            )
        raise AuthorizationFailure(403, "CSRF protection: cross-site fetch blocked")

    # 2. Origin and Referer validation
    origin = headers.get("origin")
    if not origin:
        referer = headers.get("referer")
        if referer:
            try:
                parsed = urlsplit(referer)
                origin = f"{parsed.scheme}://{parsed.netloc}"
            except Exception:
                origin = None

    allowed_origins = set()
    if settings:
        if getattr(settings, "app_env", None) is not Environment.PRODUCTION:
            allowed_origins.add(f"http://{settings.host}:{settings.port}")
            allowed_origins.add(f"http://127.0.0.1:{settings.port}")
            allowed_origins.add(f"http://localhost:{settings.port}")
            allowed_origins.add(f"https://{settings.host}:{settings.port}")
            allowed_origins.add(f"https://127.0.0.1:{settings.port}")
            allowed_origins.add(f"https://localhost:{settings.port}")
        if hasattr(settings, "allowed_origins") and settings.allowed_origins:
            allowed_origins.update(settings.allowed_origins)
    else:
        allowed_origins = {"http://127.0.0.1:8000", "http://localhost:8000"}

    if origin:
        if origin not in allowed_origins:
            if hasattr(request.app.state, "audit_sink"):
                request.app.state.audit_sink.record(
                    new_event("csrf_protection", "denied", request_id, resource=request.url.path)
                )
            raise AuthorizationFailure(403, f"CSRF protection: untrusted origin '{origin}'")
    else:
        # Missing origin information on cookie-authenticated state mutation
        if hasattr(request.app.state, "audit_sink"):
            request.app.state.audit_sink.record(
                new_event("csrf_protection", "denied", request_id, resource=request.url.path)
            )
        raise AuthorizationFailure(403, "CSRF protection: missing origin information")

    # 3. Double-Submit Anti-CSRF Token check (for non-login mutating routes)
    if not request.url.path.endswith("/auth/login"):
        csrf_header = headers.get("x-csrf-token") or headers.get("X-CSRF-Token")
        csrf_cookie = cookies.get("assistant_csrf")
        if not csrf_header or not csrf_cookie or not secrets.compare_digest(csrf_header, csrf_cookie):
            if hasattr(request.app.state, "audit_sink"):
                request.app.state.audit_sink.record(
                    new_event("csrf_protection", "denied", request_id, resource=request.url.path)
                )
            raise AuthorizationFailure(403, "CSRF protection: missing or invalid anti-CSRF token")


def current_identity(request: Request) -> Identity:
    validate_csrf(request)
    try:
        token = bearer_token(request)
        identity = request.app.state.authenticator.authenticate(token)
    except AuthenticationFailure as error:
        request.app.state.audit_sink.record(
            new_event("authentication", "denied", request.state.request_id, resource=request.url.path)
        )
        raise AuthorizationFailure(401, "Authentication required") from error
    request.app.state.audit_sink.record(
        new_event("authentication", "allowed", request.state.request_id, identity.subject, request.url.path)
    )
    return identity


def require_permission(permission: str) -> Callable[[Request], Identity]:
    def dependency(request: Request) -> Identity:
        identity = current_identity(request)
        decision = "allowed" if permission in identity.permissions else "denied"
        request.app.state.audit_sink.record(
            new_event(
                "authorization",
                decision,
                request.state.request_id,
                identity.subject,
                f"{request.url.path}:{permission}",
            )
        )
        if decision == "denied":
            raise AuthorizationFailure(403, "Permission denied")
        return identity

    return dependency
