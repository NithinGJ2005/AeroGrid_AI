"""Validated, centralized application configuration."""

from __future__ import annotations

import os
import sys
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class AuthMode(str, Enum):
    DEVELOPMENT = "development"
    LOCAL = "local"
    OIDC = "oidc"


ALLOWED_PERMISSIONS = frozenset(
    {
        "chat:use",
        "documents:search",
        "database:read",
        "admin:diagnostics",
        "engineering:read",
        "hr:read",
        "users:read",
        "users:write",
        "audit:read",
    }
)


class Settings(BaseSettings):
    """Settings loaded only from environment variables or an explicitly supplied env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Environment = Environment.DEVELOPMENT
    app_name: str = "Enterprise Intranet Assistant"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    web_concurrency: int = Field(default=1, ge=1, le=32)
    secret_key: SecretStr = Field(min_length=32)
    enable_development_auth: bool = True
    auth_mode: AuthMode = AuthMode.DEVELOPMENT
    auth_audience: str = Field(default="enterprise-intranet-assistant", min_length=1)
    auth_db_path: Path = Field(default=Path("auth.sqlite3"))
    admin_initial_password: SecretStr | None = None
    allowed_origins: list[str] = Field(default_factory=lambda: ["http://127.0.0.1:8000", "http://localhost:8000"])
    password_hash_iterations: int = Field(default=600_000, ge=100_000, le=2_000_000)
    dev_auth_signing_key: SecretStr | None = None
    oidc_issuer: str | None = None
    oidc_jwks_url: str | None = None
    role_permission_map: dict[str, list[str]] = Field(default_factory=dict)
    session_expiry_minutes: int = Field(default=480, ge=5, le=10080)
    audit_log_path: Path | None = None
    audit_retention_days: int = Field(default=365, ge=1)
    database_url: str | None = None
    database_read_only: bool = True
    database_query_timeout_seconds: int = Field(default=10, ge=1, le=300)
    database_max_result_rows: int = Field(default=100, ge=1, le=1000)
    document_roots: list[Path] = Field(default_factory=list)
    document_chunk_size: int = Field(default=800, ge=100, le=5000)
    document_chunk_overlap: int = Field(default=120, ge=0, le=1000)
    llm_enabled: bool = False
    llm_base_url: str | None = None
    llm_allowed_hosts: list[str] = Field(default_factory=list)
    llm_model: str = Field(default="qwen2.5:1.5b", min_length=1)
    llm_max_output_tokens: int = Field(default=512, ge=1, le=4096)
    llm_context_budget_tokens: int = Field(default=4096, ge=256, le=32768)
    llm_request_timeout_seconds: int = Field(default=60, ge=1, le=600)
    llm_max_concurrent_generations: int = Field(default=2, ge=1, le=256)
    llm_max_queue_depth: int = Field(default=10, ge=0, le=10000)
    llm_max_queue_wait_seconds: int = Field(default=30, ge=0, le=600)
    llm_internal_only: bool = True
    orchestration_max_iterations: int = Field(default=3, ge=1, le=10)
    anyio_thread_limiter: int = Field(default=60, ge=10, le=1000, description="AnyIO thread pool limiter per process (default 60)")
    dev_demo_accounts: list[dict[str, Any]] = Field(
        default_factory=lambda: [
            {"username": "alice.chen", "label": "Alice Chen (Engineer)", "roles": ["engineer"], "full_name": "Alice Chen", "password": os.environ.get("DEV_DEMO_PASSWORD_ALICE", "EngineeringLead2026!")},
            {"username": "david.miller", "label": "David Miller (HR)", "roles": ["hr"], "full_name": "David Miller", "password": os.environ.get("DEV_DEMO_PASSWORD_DAVID", "HRPartner2026!")},
            {"username": "bob.smith", "label": "Bob Smith (Employee)", "roles": ["employee"], "full_name": "Bob Smith", "password": os.environ.get("DEV_DEMO_PASSWORD_BOB", "StaffEngineer2026!")},
            {"username": "emma.watson", "label": "Emma Watson (Analyst)", "roles": ["analyst"], "full_name": "Emma Watson", "password": os.environ.get("DEV_DEMO_PASSWORD_EMMA", "FinanceAnalyst2026!")},
            {"username": "admin.system", "label": "Admin (Security)", "roles": ["admin"], "full_name": "Security Administrator", "password": os.environ.get("DEV_DEMO_ADMIN_PASSWORD", "AdminSecurity2026!")},
        ],
        description="Explicit development-only demo accounts. Strictly purged in production.",
    )

    @field_validator("web_concurrency", mode="before")
    @classmethod
    def resolve_web_concurrency(cls, v: Any) -> int:
        if v is not None and v != 1:
            try:
                return max(1, int(v))
            except (ValueError, TypeError):
                pass
        env_val = os.environ.get("WEB_CONCURRENCY")
        if env_val and env_val.strip().isdigit():
            return max(1, int(env_val.strip()))
        try:
            import sys
            args = sys.argv
            for i, arg in enumerate(args):
                if arg in ("--workers", "-w") and i + 1 < len(args) and args[i + 1].isdigit():
                    return max(1, int(args[i + 1]))
                if arg.startswith("--workers="):
                    part = arg.split("=", 1)[1].strip()
                    if part.isdigit():
                        return max(1, int(part))
        except Exception:
            pass
        return 1

    @field_validator("role_permission_map")
    @classmethod
    def validate_role_permission_map(cls, role_map: dict[str, list[str]]) -> dict[str, list[str]]:
        invalid = {permission for values in role_map.values() for permission in values if permission not in ALLOWED_PERMISSIONS}
        if invalid:
            raise ValueError(f"ROLE_PERMISSION_MAP contains unsupported permissions: {sorted(invalid)}")
        return role_map

    @model_validator(mode="after")
    def production_security_invariants(self) -> "Settings":
        if self.app_env is Environment.PRODUCTION or not self.enable_development_auth:
            self.dev_demo_accounts = []
        if self.app_env is Environment.PRODUCTION:
            if self.debug:
                raise ValueError("DEBUG must be false in production")
            if self.enable_development_auth:
                raise ValueError("ENABLE_DEVELOPMENT_AUTH must be false in production")
            if self.auth_mode not in (AuthMode.OIDC, AuthMode.LOCAL):
                raise ValueError("AUTH_MODE must be oidc or local in production")
            if self.auth_mode is AuthMode.OIDC:
                if not all((self.oidc_issuer, self.oidc_jwks_url)):
                    raise ValueError("OIDC_ISSUER and OIDC_JWKS_URL are required when AUTH_MODE is oidc in production")
                if not self.oidc_issuer.startswith("https://") or not self.oidc_jwks_url.startswith("https://"):
                    raise ValueError("OIDC endpoints must use HTTPS in production")
            if not self.audit_log_path:
                raise ValueError("AUDIT_LOG_PATH is required in production")
            if not self.llm_enabled or not self.llm_base_url:
                raise ValueError("LLM_ENABLED=true and LLM_BASE_URL are required in production")
            if not self.llm_allowed_hosts:
                raise ValueError("LLM_ALLOWED_HOSTS is required in production")
            if self.secret_key.get_secret_value() in (
                "enterprise-intranet-assistant-secret-key-32chars",
                "s" * 32,
                "d" * 32,
            ):
                raise ValueError("Default demonstration secret_key is not permitted in production")
            if self.password_hash_iterations < 600_000:
                raise ValueError("PASSWORD_HASH_ITERATIONS must be at least 600,000 in production")
            if not self.allowed_origins:
                raise ValueError("ALLOWED_ORIGINS must be configured in production")
        if self.auth_mode is AuthMode.DEVELOPMENT:
            if not self.enable_development_auth:
                raise ValueError("ENABLE_DEVELOPMENT_AUTH must be true when AUTH_MODE is development")
            if self.dev_auth_signing_key is None:
                raise ValueError("DEV_AUTH_SIGNING_KEY is required for development authentication")
        if not self.database_read_only:
            raise ValueError("DATABASE_READ_ONLY must remain true; write access is not supported")
        if self.document_chunk_overlap >= self.document_chunk_size:
            raise ValueError("DOCUMENT_CHUNK_OVERLAP must be smaller than DOCUMENT_CHUNK_SIZE")
        if self.llm_enabled and not self.llm_base_url:
            raise ValueError("LLM_BASE_URL is required when LLM_ENABLED is true")
        if self.llm_enabled:
            hostname = urlsplit(self.llm_base_url).hostname
            allowed_hosts = {host.lower() for host in self.llm_allowed_hosts}
            if not hostname or hostname.lower() not in allowed_hosts:
                raise ValueError("LLM_BASE_URL host must be listed in LLM_ALLOWED_HOSTS")
        if not self.llm_internal_only:
            raise ValueError("LLM_INTERNAL_ONLY must remain true")
        if self.web_concurrency > self.llm_max_concurrent_generations:
            raise ValueError(
                f"Unsupported concurrency configuration: WEB_CONCURRENCY ({self.web_concurrency}) "
                f"exceeds LLM_MAX_CONCURRENT_GENERATIONS ({self.llm_max_concurrent_generations}). "
                f"Under process-isolated admission control, each worker process requires at least 1 "
                f"active slot, which would silently multiply aggregate active generations to {self.web_concurrency}, "
                f"exceeding the global hardware budget of {self.llm_max_concurrent_generations}. "
                f"Either increase LLM_MAX_CONCURRENT_GENERATIONS to at least {self.web_concurrency} "
                f"or reduce WEB_CONCURRENCY to at most {self.llm_max_concurrent_generations}."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return process-wide settings after validation."""
    return Settings()
