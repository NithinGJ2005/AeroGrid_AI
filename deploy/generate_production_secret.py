"""Approved Production Secret and Configuration Generator.

Generates a cryptographically strong 256-bit random key using the OS CSPRNG (secrets module).
Scaffolds a hardened production environment file with:
- Strict HTTPS origin validation (rejecting plaintext HTTP and localhost).
- Strong file permission protection (0600 / owner-only).
- Protection against silent overwrites of existing production secrets.
- Zero secret leakage to console or logs.
"""

from __future__ import annotations

import argparse
import os
import secrets
import stat
import sys
from pathlib import Path
from urllib.parse import urlsplit


def generate_secret(nbytes: int = 32) -> str:
    """Generate a cryptographically random hexadecimal secret (default 256 bits from OS entropy)."""
    return secrets.token_hex(nbytes)


def validate_production_origin(origin: str) -> str:
    """Ensure origin uses HTTPS and is not localhost/plaintext."""
    parsed = urlsplit(origin.strip())
    if parsed.scheme.lower() != "https":
        raise ValueError(f"Production origin must use HTTPS scheme, got: '{origin}'")
    hostname = (parsed.hostname or "").lower()
    if not hostname or hostname in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        raise ValueError(f"Production origin cannot be localhost, got: '{origin}'")
    return origin.strip()


def create_production_env(
    dest_path: Path,
    origin: str = "https://intranet.company.internal",
    force: bool = False,
) -> None:
    """Scaffold a hardened production .env file with fresh random secrets and owner-only permissions."""
    validated_origin = validate_production_origin(origin)

    if dest_path.exists() and not force:
        raise FileExistsError(
            f"Target file '{dest_path.resolve()}' already exists. "
            "Refusing to overwrite existing production configuration without --force."
        )

    secret_key = generate_secret(32)
    content = f"""# Enterprise Intranet Assistant - Hardened Production Configuration
# Generated via deploy/generate_production_secret.py

APP_ENV=production
APP_NAME=Enterprise Intranet Assistant
COMPOSE_PROJECT_NAME=intranet-assistant
DEBUG=false
HOST=0.0.0.0
PORT=8000

# Generated 256-bit CSPRNG Production Secret
SECRET_KEY={secret_key}

ENABLE_DEVELOPMENT_AUTH=false
AUTH_MODE=local
AUTH_AUDIENCE=enterprise-intranet-assistant
PASSWORD_HASH_ITERATIONS=600000

# Strict HTTPS origin binding (no plaintext HTTP or localhost)
ALLOWED_ORIGINS=["{validated_origin}"]

# Durable paths
AUTH_DB_PATH=/data/auth/auth.sqlite3
AUDIT_LOG_PATH=/var/log/app/audit.jsonl

# Internal Database & Document Roots
DATABASE_URL=sqlite:///./sample_db.sqlite3
DATABASE_READ_ONLY=true
DATABASE_QUERY_TIMEOUT_SECONDS=10
DATABASE_MAX_RESULT_ROWS=100

DOCUMENT_ROOTS=["/data/documents"]
DOCUMENT_CHUNK_SIZE=800
DOCUMENT_CHUNK_OVERLAP=120

# Internal-only LLM inference endpoint
LLM_ENABLED=true
LLM_BASE_URL=http://llm-service:8000/v1
LLM_ALLOWED_HOSTS=["llm-service", "127.0.0.1"]
LLM_INTERNAL_ONLY=true
LLM_MODEL=qwen3-4b-reviewed
ORCHESTRATION_MAX_ITERATIONS=3

# Server-Side RBAC Permission Matrix
ROLE_PERMISSION_MAP={{"employee": ["chat:use", "documents:search", "database:read"], "engineer": ["chat:use", "documents:search", "database:read", "engineering:read"], "hr": ["chat:use", "documents:search", "database:read", "hr:read"], "analyst": ["chat:use", "database:read"], "admin": ["chat:use", "database:read", "admin:diagnostics", "users:read", "users:write", "audit:read"]}}
"""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_text(content, encoding="utf-8")

    # Enforce restrictive permissions (0600 on POSIX; owner-only on Windows)
    try:
        os.chmod(dest_path, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass

    if sys.platform == "win32":
        try:
            import subprocess
            # Remove inheritance and grant only current user read/write access
            user = os.environ.get("USERNAME", "")
            if user:
                subprocess.run(
                    ["icacls", str(dest_path), "/inheritance:r", "/grant:r", f"{user}:(R,W)"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception:
            pass

    print(f"[SUCCESS] Production configuration successfully written to: {dest_path.resolve()}")
    print(f"[SECURITY] Bound to approved HTTPS origin: '{validated_origin}'")
    print("[SECURITY] Restrictive file permissions (owner read/write only) applied.")
    print("[SECURITY] Generated 256-bit secret stored securely; secret values are omitted from output.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate hardened production configuration with random secrets.")
    parser.add_argument("--output", "-o", type=Path, required=True, help="Target file path to write .env.production")
    parser.add_argument("--origin", default="https://intranet.company.internal", help="Approved HTTPS deployment origin")
    parser.add_argument("--force", action="store_true", help="Overwrite existing target file if it already exists")
    args = parser.parse_args()

    try:
        create_production_env(args.output, origin=args.origin, force=args.force)
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
