"""Durable SQLite account management, password hashing, and session revocation.

Implements an air-gapped, zero-external-dependency identity store backed by SQLite
with WAL mode for multi-worker consistency, PBKDF2-HMAC-SHA256 salted password hashing
(OWASP-recommended 600,000 iterations), transparent hash parameter migration, durable
brute-force lockout protections, administrative role provisioning, fine-grained change
auditing, and durable session revocation tracking.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from pathlib import Path
import re
from typing import Any
import urllib.error
import urllib.request

DEFAULT_ITERATIONS = 600_000
LOCKOUT_ATTEMPTS = 5
LOCKOUT_DURATION_SECONDS = 900.0  # 15 minutes

DEFAULT_DEV_DEMO_ACCOUNTS: list[dict[str, Any]] = [
    {"username": "alice.chen", "label": "Alice Chen (Engineer)", "roles": ["engineer"], "full_name": "Alice Chen", "password": os.environ.get("DEV_DEMO_PASSWORD_ALICE", "EngineeringLead2026!")},
    {"username": "david.miller", "label": "David Miller (HR)", "roles": ["hr"], "full_name": "David Miller", "password": os.environ.get("DEV_DEMO_PASSWORD_DAVID", "HRPartner2026!")},
    {"username": "bob.smith", "label": "Bob Smith (Employee)", "roles": ["employee"], "full_name": "Bob Smith", "password": os.environ.get("DEV_DEMO_PASSWORD_BOB", "StaffEngineer2026!")},
    {"username": "emma.watson", "label": "Emma Watson (Analyst)", "roles": ["analyst"], "full_name": "Emma Watson", "password": os.environ.get("DEV_DEMO_PASSWORD_EMMA", "FinanceAnalyst2026!")},
    {"username": "admin.system", "label": "Admin (Security)", "roles": ["admin"], "full_name": "Security Administrator", "password": os.environ.get("DEV_DEMO_ADMIN_PASSWORD", "AdminSecurity2026!")},
]


@dataclass
class UserAccount:
    """Represents an administratively provisioned employee account."""

    username: str
    full_name: str
    password_hash: str
    salt: str
    roles: list[str]
    is_active: bool = True
    failed_login_attempts: int = 0
    locked_until: float = 0.0
    iterations: int = DEFAULT_ITERATIONS
    token_version: int = 1
    is_demo: bool = False
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "username": self.username,
            "full_name": self.full_name,
            "roles": list(self.roles),
            "is_active": self.is_active,
            "is_demo": self.is_demo,
        }


def hash_password(
    password: str, salt: str | None = None, iterations: int = DEFAULT_ITERATIONS
) -> tuple[str, str, int]:
    """Hash a password using PBKDF2-HMAC-SHA256 with given iterations and a random salt."""
    if salt is None:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    return key.hex(), salt, iterations


def verify_password(
    password: str, password_hash: str, salt: str, iterations: int = DEFAULT_ITERATIONS
) -> bool:
    """Verify candidate password against stored PBKDF2 hash using constant-time comparison."""
    candidate_hash, _, _ = hash_password(password, salt, iterations)
    return hmac.compare_digest(candidate_hash, password_hash)


TICKET_REGEX = re.compile(r"^(SEC|CHG|OPS)-\d{4,}(-[A-Z0-9]+)+$")
APPROVAL_REF_REGEX = re.compile(
    r"^(CAB-APP|SEC-APPR|ITSM-APPR|ITSM-API-VERIFIED|CAB)-\d{4,}(-[A-Z0-9]+)+$|^ITSM-API-VERIFIED:[A-Z_]+$"
)


def validate_ticket_format(ticket: str) -> bool:
    """Validate organizational change management ticket format (format verification only, not approval)."""
    if not ticket or not isinstance(ticket, str):
        return False
    return bool(TICKET_REGEX.match(ticket.strip()))


def validate_approval_reference_format(approval_ref: str) -> bool:
    """Validate formal CAB or Security approval reference format, strictly rejecting arbitrary strings."""
    if not approval_ref or not isinstance(approval_ref, str):
        return False
    return bool(APPROVAL_REF_REGEX.match(approval_ref.strip()))


AUTHORIZED_OPERATOR_GROUPS = frozenset({"sudo", "wheel", "secops", "admin"})

AUTHORIZED_CHANGE_APPROVERS = frozenset({
    "cab_chair_morris",
    "secops_lead_carol",
    "change_manager_davis",
    "cab.authority",
    "secops.lead",
})

DEFAULT_PRODUCTION_APPROVERS_CONFIG = Path("/etc/intranet-assistant/authorized_approvers.json")


def get_authorized_change_approvers(
    config_path: str | Path | None = None,
    is_production: bool | None = None,
) -> frozenset[str]:
    """Retrieve authorized change approver usernames from trusted deployment configuration.

    Trust boundary & configuration integrity:
    1. Explicit Trusted Production Location:
       In production (is_production is True or APP_ENV/ENVIRONMENT=='production'), approver policy
       must be loaded from a trusted, deployment-controlled configuration file
       (config_path, APPROVERS_CONFIG_FILE, or DEFAULT_PRODUCTION_APPROVERS_CONFIG = /etc/intranet-assistant/authorized_approvers.json).
       Silent fallback to development constants or untrusted environment strings is strictly prohibited in production.
    2. File Ownership & Permissions on POSIX:
       If running on POSIX systems, the configuration file must not be world-writable (mode & 0o002)
       or group-writable (mode & 0o020). When executed with root privileges, the file and any symlinks
       must be owned by root (UID 0) to prevent unprivileged users from modifying or replacing the configuration.
    3. Strict Formatting & Fail-Closed:
       Usernames must match ^[a-zA-Z0-9_.-]{3,64}$. Wildcards (*), empty lists, unreadable files,
       or invalid entries fail closed immediately.
    4. Allowlist vs Authentication:
       Membership in this allowlist is an authorization gate under CAB policy. It does NOT constitute
       cryptographic authentication of the approver. In air-gapped manual verification, the executing
       operator must independently verify physical/signed CAB evidence and attest to out-of-band verification.
    """
    if is_production is None:
        is_prod = (
            os.environ.get("APP_ENV", "").strip().lower() == "production"
            or os.environ.get("ENVIRONMENT", "").strip().lower() == "production"
        )
    else:
        is_prod = is_production

    target_config = config_path or os.environ.get("APPROVERS_CONFIG_FILE", "").strip()

    # In production, default to DEFAULT_PRODUCTION_APPROVERS_CONFIG if not explicitly overridden
    if is_prod and not target_config:
        target_config = str(DEFAULT_PRODUCTION_APPROVERS_CONFIG)

    if target_config:
        cfg = Path(target_config)
        if not cfg.exists():
            raise FileNotFoundError(
                f"Trusted approver configuration file not found: '{target_config}'. "
                f"Silent fallback to development constants or untrusted environment variables is prohibited. "
                f"Procedure fails closed."
            )

        # Check POSIX filesystem security invariants
        if os.name == "posix":
            # Check symlink safety
            if cfg.is_symlink():
                lstat = cfg.lstat()
                if hasattr(os, "geteuid") and os.geteuid() == 0 and lstat.st_uid != 0:
                    raise PermissionError(
                        f"Insecure approver configuration symlink '{cfg}': symlink is owned by UID {lstat.st_uid}, "
                        f"expected root (UID 0). Procedure fails closed."
                    )
            st = cfg.stat()
            # Unprivileged users cannot modify or replace configuration: must not be world- or group-writable
            if st.st_mode & 0o002:
                raise PermissionError(
                    f"Insecure approver configuration permissions on '{cfg}': file is world-writable ({oct(st.st_mode)}). "
                    f"Unprivileged users must not have write access. Procedure fails closed."
                )
            if st.st_mode & 0o020:
                raise PermissionError(
                    f"Insecure approver configuration permissions on '{cfg}': file is group-writable ({oct(st.st_mode)}). "
                    f"Unprivileged users must not have write access. Procedure fails closed."
                )
            # When running as root, verify root ownership
            if hasattr(os, "geteuid") and os.geteuid() == 0 and st.st_uid != 0:
                raise PermissionError(
                    f"Insecure approver configuration ownership on '{cfg}': file is owned by UID {st.st_uid}, "
                    f"expected root (UID 0). Procedure fails closed."
                )

        try:
            content = cfg.read_text(encoding="utf-8")
            if content.strip().startswith("["):
                items = json.loads(content)
            else:
                items = [
                    line.strip()
                    for line in re.split(r"[\n,]+", content)
                    if line.strip() and not line.strip().startswith("#")
                ]
            valid_approvers = set()
            for item in items:
                name = str(item).strip().lower()
                if not name or name == "*" or not re.match(r"^[a-zA-Z0-9_.-]{3,64}$", name):
                    raise ValueError(f"Invalid approver format or wildcard in approver config: '{item}'")
                valid_approvers.add(name)
            if not valid_approvers:
                raise ValueError(f"Approver configuration file '{target_config}' contains no valid approvers.")
            return frozenset(valid_approvers)
        except Exception as e:
            raise ValueError(f"Failed to load trusted approver configuration from '{target_config}': {e}") from e

    # In production, silent fallback to environment variables or constants is strictly prohibited
    if is_prod:
        raise ValueError(
            "Production approver configuration missing: Production deployments require an explicit trusted "
            "approver configuration file (e.g., /etc/intranet-assistant/authorized_approvers.json). "
            "Silent fallback to development constants or untrusted environment variables is prohibited in production. "
            "Procedure fails closed."
        )

    if "AUTHORIZED_CHANGE_APPROVERS" in os.environ:
        raw = os.environ.get("AUTHORIZED_CHANGE_APPROVERS", "").strip()
        if not raw:
            raise ValueError("Invalid approver configuration: AUTHORIZED_CHANGE_APPROVERS is set but empty. Procedure fails closed.")
        parsed = set()
        for token in raw.split(","):
            t = token.strip().lower()
            if not t or t == "*" or not re.match(r"^[a-zA-Z0-9_.-]{3,64}$", t):
                raise ValueError(f"Invalid approver name or wildcard detected in AUTHORIZED_CHANGE_APPROVERS: '{token.strip()}'. Procedure fails closed.")
            parsed.add(t)
        if not parsed:
            raise ValueError("No valid approvers parsed from AUTHORIZED_CHANGE_APPROVERS.")
        return frozenset(parsed)

    return AUTHORIZED_CHANGE_APPROVERS


def resolve_trusted_operator_identity(
    candidate_operator: str | None = None,
    allow_posix_kernel_audit: bool = True,
    operator_group_lookup: dict[str, list[str]] | None = None,
) -> str:
    """Resolve and verify operator identity using trusted host execution and audit mechanisms.

    Fails closed if the operator cannot be identified, does not match the kernel audit
    loginuid / PAM session, is root/nobody, or is not in authorized administrative groups.
    Does not treat an arbitrary SUDO_USER environment value as sufficient proof of identity.
    Strictly rejects unset/invalid kernel login UIDs, direct root logins, and missing sudo metadata.
    """
    try:
        import pwd
        import grp
        is_posix = True
    except ImportError:
        is_posix = False

    if is_posix and allow_posix_kernel_audit:
        if os.geteuid() != 0:
            raise PermissionError("Privileged admin provisioning must be executed with root permissions via sudo.")

        # 1. Inspect Linux kernel audit subsystem loginuid (/proc/self/loginuid)
        loginuid_user: str | None = None
        loginuid_int: int | None = None
        loginuid_path = Path("/proc/self/loginuid")
        if loginuid_path.exists():
            try:
                raw_uid = loginuid_path.read_text(encoding="utf-8").strip()
                loginuid_int = int(raw_uid)
            except Exception as e:
                raise ValueError(f"Invalid or unreadable kernel audit loginuid. Procedure fails closed: {e}") from e

            if loginuid_int == 4294967295 or loginuid_int < 0:
                raise ValueError(
                    f"Unset or invalid kernel audit loginuid ({loginuid_int}). "
                    f"Privileged operations require an authenticated kernel audit session. Procedure fails closed."
                )
            if loginuid_int == 0:
                raise ValueError(
                    "Direct root login is prohibited: Privileged admin provisioning must be "
                    "invoked via sudo by an authenticated, named individual operator."
                )
            try:
                pw_login = pwd.getpwuid(loginuid_int)
                loginuid_user = pw_login.pw_name
            except KeyError as e:
                raise ValueError(f"Kernel audit loginuid {loginuid_int} does not exist in host user database.") from e

        # 2. Inspect SUDO_USER and SUDO_UID from PAM/sudo execution
        sudo_user = os.environ.get("SUDO_USER", "").strip()
        sudo_uid_str = os.environ.get("SUDO_UID", "").strip()

        if not sudo_user or not sudo_uid_str:
            raise ValueError(
                "Missing sudo invocation metadata (SUDO_USER/SUDO_UID): Direct root execution "
                "without sudo session metadata is prohibited. Privileged operations must be executed via sudo."
            )

        if sudo_user.lower() in ("root", "nobody", "daemon", "unknown"):
            raise ValueError(
                "Direct root login or system daemon invocation is prohibited: Privileged admin "
                "provisioning must be invoked via sudo by an authenticated, named individual operator."
            )

        try:
            pw_sudo = pwd.getpwnam(sudo_user)
        except KeyError as e:
            raise ValueError(f"SUDO_USER '{sudo_user}' does not exist in host user database.") from e

        if str(pw_sudo.pw_uid) != sudo_uid_str:
            raise ValueError(
                f"Operator identity spoofing detected: SUDO_USER '{sudo_user}' UID mismatch "
                f"(expected {pw_sudo.pw_uid}, got SUDO_UID {sudo_uid_str}). Procedure fails closed."
            )

        # 3. Cross-verify SUDO_USER against kernel audit loginuid to prevent env variable spoofing
        if loginuid_user:
            if sudo_user != loginuid_user:
                raise ValueError(
                    f"Operator identity spoofing detected: SUDO_USER '{sudo_user}' does not match "
                    f"kernel audit loginuid '{loginuid_user}'. Procedure fails closed."
                )
            if loginuid_int is not None and str(loginuid_int) != sudo_uid_str:
                raise ValueError(
                    f"Operator identity spoofing detected: kernel audit loginuid {loginuid_int} "
                    f"does not match SUDO_UID {sudo_uid_str}. Procedure fails closed."
                )

        resolved_operator = sudo_user

        if candidate_operator:
            cand_clean = candidate_operator.strip()
            if cand_clean != resolved_operator:
                raise ValueError(
                    f"Operator attribution mismatch: Provided operator '{cand_clean}' does not match "
                    f"trusted host execution identity '{resolved_operator}'. Procedure fails closed."
                )

        if not resolved_operator or resolved_operator.lower() in ("root", "nobody", "daemon", "unknown"):
            raise ValueError(
                "Missing or unauthorized host operator identity: Privileged provisioning must be "
                "invoked via sudo by an authenticated, named individual operator."
            )

        pw_entry = pw_sudo
        user_groups = [g.gr_name for g in grp.getgrall() if resolved_operator in g.gr_mem]
        try:
            user_groups.append(grp.getgrgid(pw_entry.pw_gid).gr_name)
        except KeyError:
            pass

        if not any(g in AUTHORIZED_OPERATOR_GROUPS for g in user_groups):
            allowed_groups_str = ", ".join(sorted(AUTHORIZED_OPERATOR_GROUPS))
            raise PermissionError(
                f"Operator '{resolved_operator}' is not authorized: must belong to one of "
                f"({allowed_groups_str}). Procedure fails closed."
            )

        return resolved_operator

    # Non-POSIX / testing fallback
    op = (candidate_operator or os.environ.get("SUDO_USER") or "").strip()
    if not op:
        import getpass
        try:
            op = getpass.getuser()
        except Exception:
            op = ""
    if not op or op.lower() in ("root", "nobody", "daemon", "unknown"):
        raise ValueError(
            "Missing or unauthorized host operator identity: Privileged provisioning requires an "
            "authenticated, named operator. Procedure fails closed."
        )

    if operator_group_lookup is not None:
        groups = operator_group_lookup.get(op, [])
        if not any(g in AUTHORIZED_OPERATOR_GROUPS for g in groups):
            allowed_groups_str = ", ".join(sorted(AUTHORIZED_OPERATOR_GROUPS))
            raise PermissionError(
                f"Operator '{op}' is not authorized: must belong to one of "
                f"({allowed_groups_str}). Procedure fails closed."
            )

    return op


def verify_change_approval(
    ticket: str,
    approval_ref: str,
    operator: str,
    independent_approver: str | None = None,
    authorized_approvers: set[str] | frozenset[str] | None = None,
    itsm_url: str | None = None,
    itsm_token: str | None = None,
    itsm_client: Any = None,
    manual_attestation: bool = False,
    operator_verifier: Any = None,
    config_path: str | Path | None = None,
    is_production: bool | None = None,
) -> dict[str, Any]:
    """Verify ticket status and approval reference distinguishing ticket-format validation from authorization.

    Enforces that:
    1. Ticket format validation alone is not approval.
    2. If an approved ITSM integration exists (itsm_client or ITSM_API_URL/ITSM_API_TOKEN),
       it actively queries the ITSM integration to verify ticket existence (not 404),
       approved/implementing status (not rejected/cancelled/draft), matching target system,
       and matching approval reference. Network errors and invalid responses fail closed.
       It cross-checks that the ITSM approver did not self-approve and matches any supplied approver.
    3. If no ITSM integration exists (air-gapped staging), a two-person rule (segregation of duties)
       is strictly enforced: the operator executing the change cannot be their own approver.
       An independent change approver (CAB Chair or SecOps Lead) must be specified and cannot match
       the operator. The approver's authorization is verified against authorized change approvers;
       a different user-supplied name is not automatically considered authenticated approval.
       The approval reference cannot be an arbitrary string and must match formal CAB/Security
       reference patterns (supplementary format validation), and the operator must explicitly confirm
       out-of-band portal verification.
    4. Operator identity must be an authenticated non-root, non-nobody named operator verified
       by trusted host execution and audit mechanisms.
    """
    clean_ticket = (ticket or "").strip()
    clean_ref = (approval_ref or "").strip()
    clean_op = (operator or "").strip()
    clean_approver = (independent_approver or "").strip()

    trusted_deployment_approvers = get_authorized_change_approvers(
        config_path=config_path,
        is_production=is_production,
    )
    if authorized_approvers is not None:
        caller_set = {a.strip().lower() for a in authorized_approvers if a.strip()}
        untrusted = caller_set - trusted_deployment_approvers
        if untrusted:
            untrusted_str = ", ".join(sorted(untrusted))
            raise PermissionError(
                f"Approver authorization bypass attempt detected: '{untrusted_str}' is not in the "
                f"trusted deployment-controlled change approver registry. Procedure fails closed."
            )
        allowed_approver_set = caller_set
    else:
        allowed_approver_set = trusted_deployment_approvers

    if not clean_ticket:
        raise ValueError("Missing change ticket: Privileged admin provisioning requires an organizational change ticket.")

    if not validate_ticket_format(clean_ticket):
        raise ValueError(
            f"Invalid ticket format '{clean_ticket}': Ticket must match organizational format "
            f"(SEC-XXXX-YYY, CHG-YYYYMMDD-XXX, or OPS-XXXX-YYY). Ticket format validation alone is not approval."
        )

    if operator_verifier is not None:
        if callable(operator_verifier):
            clean_op = operator_verifier(clean_op)
        elif isinstance(operator_verifier, dict):
            clean_op = resolve_trusted_operator_identity(
                candidate_operator=clean_op,
                allow_posix_kernel_audit=False,
                operator_group_lookup=operator_verifier,
            )
    else:
        if not clean_op or clean_op.lower() in ("root", "nobody", "daemon", "unknown"):
            raise ValueError("Missing or unauthorized host operator identity: Privileged provisioning requires verified operator audit attribution.")

    if not clean_ref:
        raise ValueError(f"Missing approval evidence for ticket '{clean_ticket}': Ticket format validation alone is not approval.")

    # Supplementary format check: arbitrary strings are rejected
    if not validate_approval_reference_format(clean_ref):
        raise ValueError(
            f"Inadequate approval evidence: '{clean_ref}' is not a recognized formal CAB/Security approval reference format "
            f"(e.g., CAB-APP-202610-092 or SEC-APPR-202610-101). Format validation alone is not approval; arbitrary reference strings are rejected."
        )

    resolved_itsm_url = (itsm_url or os.environ.get("ITSM_API_URL", "")).strip()
    resolved_itsm_token = (itsm_token or os.environ.get("ITSM_API_TOKEN", "")).strip()

    # Fail closed on incomplete configuration (URL without token)
    if resolved_itsm_url and not resolved_itsm_token and itsm_client is None:
        raise ValueError(
            f"Incomplete ITSM integration configuration: ITSM_API_URL is configured ('{resolved_itsm_url}') "
            f"but ITSM_API_TOKEN is missing. Privileged verification requires authenticated service integration. Procedure fails closed."
        )

    # Transport security check: Reject insecure HTTP for remote endpoints
    if resolved_itsm_url.startswith("http://") and not any(h in resolved_itsm_url for h in ("localhost", "127.0.0.1", ".local", "test")):
        raise ValueError(
            f"Insecure ITSM transport: ITSM_API_URL must use HTTPS in production environments ('{resolved_itsm_url}'). "
            f"Plaintext HTTP transmission of bearer tokens and approval evidence is prohibited."
        )

    has_itsm = itsm_client is not None or (bool(resolved_itsm_url) and bool(resolved_itsm_token))

    if has_itsm:
        itsm_record: dict[str, Any] | None = None
        if itsm_client is not None:
            try:
                if callable(itsm_client):
                    itsm_record = itsm_client(clean_ticket)
                elif hasattr(itsm_client, "get_change"):
                    itsm_record = itsm_client.get_change(clean_ticket)
                elif hasattr(itsm_client, "query"):
                    itsm_record = itsm_client.query(clean_ticket)
                else:
                    raise ValueError("Invalid itsm_client provided")
            except Exception as client_err:
                raise ValueError(f"ITSM verification failed: {client_err}") from client_err
        else:
            req = urllib.request.Request(
                f"{resolved_itsm_url.rstrip('/')}/api/v1/changes/{clean_ticket}",
                headers={"Authorization": f"Bearer {resolved_itsm_token}", "Accept": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    resp_data = resp.read().decode("utf-8")
                    try:
                        itsm_record = json.loads(resp_data)
                    except Exception as json_err:
                        raise ValueError(f"ITSM API error for ticket '{clean_ticket}': Response is not valid JSON ({json_err})") from json_err
            except urllib.error.HTTPError as http_err:
                if http_err.code == 404:
                    raise ValueError(f"ITSM verification failed: Ticket '{clean_ticket}' does not exist in ITSM (HTTP 404).") from http_err
                raise ValueError(f"ITSM API error for ticket '{clean_ticket}': HTTP {http_err.code} {http_err.reason}") from http_err
            except Exception as net_err:
                raise ValueError(f"ITSM API connection failed for ticket '{clean_ticket}': {net_err}") from net_err

        if itsm_record is None or not itsm_record or not isinstance(itsm_record, dict):
            raise ValueError(f"ITSM verification failed: Ticket '{clean_ticket}' does not exist in ITSM (empty or invalid record).")

        ticket_status = str(itsm_record.get("status", "")).strip().upper()
        if not ticket_status:
            raise ValueError(f"ITSM verification failed: Ticket '{clean_ticket}' record has no status.")
        if ticket_status in ("REJECTED", "CANCELLED", "DENIED", "REVOKED"):
            raise ValueError(f"ITSM verification failed: Ticket '{clean_ticket}' has been rejected in ITSM (status: {ticket_status}).")
        if ticket_status not in ("APPROVED", "IN_PROGRESS", "SCHEDULED", "IMPLEMENTING"):
            raise ValueError(f"ITSM verification failed: Ticket '{clean_ticket}' is not approved in ITSM (current status: {ticket_status}).")

        target_system = str(itsm_record.get("target_system") or "intranet-assistant").strip()
        if target_system.lower() not in ("intranet-assistant", "enterprise-intranet-assistant"):
            raise ValueError(f"ITSM verification failed: Ticket '{clean_ticket}' target system '{target_system}' does not match 'intranet-assistant'.")

        itsm_approval_id = str(itsm_record.get("approval_id") or "").strip()
        verified_ref = itsm_approval_id or f"ITSM-API-VERIFIED:{ticket_status}"

        # If operator provided a specific approval ref, ensure it doesn't contradict the ITSM approval record
        if clean_ref and itsm_approval_id and clean_ref != itsm_approval_id and not clean_ref.startswith("ITSM-API-VERIFIED:"):
            raise ValueError(
                f"ITSM verification failed: Provided approval reference '{clean_ref}' does not match "
                f"ITSM record approval ID '{itsm_approval_id}'."
            )

        itsm_approver = str(itsm_record.get("approver") or itsm_record.get("approved_by") or "").strip()
        if not itsm_approver:
            if clean_approver:
                itsm_approver = clean_approver
            else:
                raise ValueError(f"ITSM verification failed: Ticket '{clean_ticket}' record has no recorded approver and no authorized independent approver was provided. Procedure fails closed.")

        # ITSM Segregation of duties: operator cannot have approved their own ticket in ITSM
        if itsm_approver.lower() == clean_op.lower():
            raise ValueError(
                f"Segregation of duties violation: ITSM record shows change ticket '{clean_ticket}' was approved by "
                f"the operator '{clean_op}'. Self-approval is prohibited."
            )

        # Cross-reconcile with user-supplied approver if supplied
        if clean_approver and clean_approver.lower() != itsm_approver.lower():
            raise ValueError(
                f"ITSM verification failed: Supplied approver '{clean_approver}' does not match "
                f"official ITSM change approver '{itsm_approver}'."
            )

        # Verify approver is authorized in ITSM mode strictly against allowed_approver_set
        if itsm_approver.lower() not in allowed_approver_set:
            allowed_str = ", ".join(sorted(allowed_approver_set))
            raise PermissionError(
                f"ITSM approver '{itsm_approver}' is not an authorized change approver. Must be one of ({allowed_str}). Procedure fails closed."
            )

        return {
            "verified": True,
            "method": "itsm_api",
            "status": ticket_status,
            "target_system": target_system,
            "approval_ref": itsm_approval_id or clean_ref or verified_ref,
            "ticket": clean_ticket,
            "operator": clean_op,
            "independent_approver": itsm_approver,
        }

    # Manual verification path (air-gapped staging enclave)
    # Segregation of duties / Two-person rule:
    if not clean_approver:
        raise ValueError(
            "Independent approval required: Air-gapped privileged provisioning requires an independent change "
            "approver (CAB Chair or SecOps Lead) distinct from the executing operator. "
            "An operator's own attestation is not independent approval."
        )

    if clean_approver.lower() == clean_op.lower():
        raise ValueError(
            f"Segregation of duties violation: Operator '{clean_op}' cannot approve their own privileged change ticket. "
            f"An independent approver is required by change control policy."
        )

    # Verify approver authorization: a different user-supplied name is NOT automatically considered authenticated approval
    if clean_approver.lower() not in allowed_approver_set:
        allowed_str = ", ".join(sorted(allowed_approver_set))
        raise PermissionError(
            f"Approver '{clean_approver}' is not authorized to approve privileged changes. Privileged admin provisioning "
            f"requires approval from a designated CAB Chair or SecOps Lead ({allowed_str}). Procedure fails closed."
        )

    if not manual_attestation:
        raise ValueError(
            "Manual approval verification required: Authorized operator must explicitly confirm out-of-band "
            "CAB/Security change approval verification in the organizational change management portal."
        )

    return {
        "verified": True,
        "method": "air_gapped_two_person_verification",
        "status": "APPROVED",
        "target_system": "intranet-assistant",
        "approval_ref": clean_ref,
        "ticket": clean_ticket,
        "operator": clean_op,
        "independent_approver": clean_approver,
    }


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS accounts (
    username TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    roles TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    failed_login_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until REAL NOT NULL DEFAULT 0.0,
    iterations INTEGER NOT NULL DEFAULT 600000,
    token_version INTEGER NOT NULL DEFAULT 1,
    is_demo INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_revocations (
    jti TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    revoked_at TEXT NOT NULL,
    expires_at REAL NOT NULL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS admin_audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    details TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    outcome TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_revocations_expires_at ON session_revocations(expires_at);
CREATE INDEX IF NOT EXISTS idx_admin_audit_actor ON admin_audit_events(actor);
"""


class SqliteAuthStore:
    """Thread-safe and multi-worker durable SQLite store for accounts, sessions, and audits."""

    def __init__(
        self,
        db_path: str | Path = "auth.sqlite3",
        is_production: bool = False,
        iterations: int = DEFAULT_ITERATIONS,
        demo_accounts: list[dict[str, Any]] | None = None,
    ) -> None:
        self.db_path = str(db_path)
        self.is_production = is_production
        self.iterations = iterations
        if demo_accounts is None:
            self.demo_accounts = [] if is_production else list(DEFAULT_DEV_DEMO_ACCOUNTS)
        else:
            self.demo_accounts = [] if is_production else list(demo_accounts)
        self._lock = threading.Lock()
        self._memory_conn: sqlite3.Connection | None = None

        if self.db_path == ":memory:":
            self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._memory_conn.row_factory = sqlite3.Row

        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        if self._memory_conn is not None:
            return self._memory_conn
        conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("PRAGMA journal_mode=WAL;")
                with conn:
                    conn.executescript(SCHEMA_SQL)
                    # Lightweight schema migration for existing databases
                    cur = conn.execute("PRAGMA table_info(accounts);")
                    cols = {row["name"] for row in cur.fetchall()}
                    if "token_version" not in cols:
                        conn.execute("ALTER TABLE accounts ADD COLUMN token_version INTEGER NOT NULL DEFAULT 1;")
                    if "iterations" not in cols:
                        conn.execute("ALTER TABLE accounts ADD COLUMN iterations INTEGER NOT NULL DEFAULT 600000;")
                    if "is_demo" not in cols:
                        conn.execute("ALTER TABLE accounts ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0;")
                    if not self.is_production:
                        self._seed_default_accounts(conn)
            finally:
                if self._memory_conn is None:
                    conn.close()

    def _seed_default_accounts(self, conn: sqlite3.Connection) -> None:
        if self.is_production or not self.demo_accounts:
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        for item in self.demo_accounts:
            username = item.get("username")
            password = item.get("password")
            full_name = item.get("full_name") or item.get("label", username)
            roles = item.get("roles", [])
            if not username or not password:
                continue
            cur = conn.execute("SELECT username FROM accounts WHERE username = ?", (username,))
            if not cur.fetchone():
                p_hash, salt, iters = hash_password(password, iterations=self.iterations)
                conn.execute(
                    """
                    INSERT INTO accounts (username, full_name, password_hash, salt, roles, is_active, failed_login_attempts, locked_until, iterations, token_version, is_demo, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 1, 0, 0.0, ?, 1, 1, ?, ?)
                    """,
                    (username, full_name, p_hash, salt, json.dumps(roles), iters, now_iso, now_iso),
                )

    def _row_to_account(self, row: sqlite3.Row) -> UserAccount:
        roles = json.loads(row["roles"]) if row["roles"] else []
        return UserAccount(
            username=row["username"],
            full_name=row["full_name"],
            password_hash=row["password_hash"],
            salt=row["salt"],
            roles=roles,
            is_active=bool(row["is_active"]),
            failed_login_attempts=int(row["failed_login_attempts"]),
            locked_until=float(row["locked_until"]),
            iterations=int(row["iterations"]),
            token_version=int(row["token_version"]) if "token_version" in row.keys() else 1,
            is_demo=bool(row["is_demo"]) if "is_demo" in row.keys() else False,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def authenticate(self, username: str, password: str) -> UserAccount | None:
        """Authenticate user credentials with durable lockout protection and parameter migration."""
        key = username.strip().lower()
        now = time.time()

        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    cur = conn.execute("SELECT * FROM accounts WHERE username = ?", (key,))
                    row = cur.fetchone()
                    if not row:
                        return None
                    # Account metadata check: In production mode, demo accounts (is_demo=1) are rejected
                    if self.is_production and bool(row["is_demo"] if "is_demo" in row.keys() else 0):
                        return None
                    account = self._row_to_account(row)
                    if not account.is_active:
                        return None
                    if account.locked_until > now:
                        return None  # Account temporarily locked out

                    # Verify candidate password with stored iterations
                    is_valid = verify_password(
                        password, account.password_hash, account.salt, account.iterations
                    )
                    if not is_valid:
                        new_attempts = account.failed_login_attempts + 1
                        new_locked = (
                            now + LOCKOUT_DURATION_SECONDS
                            if new_attempts >= LOCKOUT_ATTEMPTS
                            else 0.0
                        )
                        conn.execute(
                            "UPDATE accounts SET failed_login_attempts = ?, locked_until = ?, updated_at = ? WHERE username = ?",
                            (new_attempts, new_locked, datetime.now(timezone.utc).isoformat(), key),
                        )
                        return None

                    # Successful authentication! Check if hash parameter upgrade is needed
                    new_hash = account.password_hash
                    new_salt = account.salt
                    new_iter = account.iterations
                    if account.iterations < self.iterations:
                        new_hash, new_salt, new_iter = hash_password(
                            password, iterations=self.iterations
                        )
                        conn.execute(
                            "INSERT INTO admin_audit_events (actor, action, target, details, timestamp, outcome) VALUES (?, ?, ?, ?, ?, ?)",
                            (
                                key,
                                "password_hash_migrated",
                                key,
                                json.dumps(
                                    {
                                        "old_iterations": account.iterations,
                                        "new_iterations": new_iter,
                                    }
                                ),
                                datetime.now(timezone.utc).isoformat(),
                                "allowed",
                            ),
                        )

                    conn.execute(
                        "UPDATE accounts SET failed_login_attempts = 0, locked_until = 0.0, password_hash = ?, salt = ?, iterations = ?, updated_at = ? WHERE username = ?",
                        (new_hash, new_salt, new_iter, datetime.now(timezone.utc).isoformat(), key),
                    )
                    account.failed_login_attempts = 0
                    account.locked_until = 0.0
                    account.password_hash = new_hash
                    account.salt = new_salt
                    account.iterations = new_iter
                    return account
            finally:
                if self._memory_conn is None:
                    conn.close()

    def get_user(self, username: str) -> UserAccount | None:
        key = username.strip().lower()
        if self._memory_conn is not None:
            with self._lock:
                cur = self._memory_conn.execute("SELECT * FROM accounts WHERE username = ?", (key,))
                row = cur.fetchone()
                return self._row_to_account(row) if row else None
        conn = self._connect()
        try:
            cur = conn.execute("SELECT * FROM accounts WHERE username = ?", (key,))
            row = cur.fetchone()
            return self._row_to_account(row) if row else None
        finally:
            conn.close()

    def list_users(self) -> list[dict[str, object]]:
        if self._memory_conn is not None:
            with self._lock:
                cur = self._memory_conn.execute("SELECT * FROM accounts ORDER BY username")
                return [self._row_to_account(row).to_dict() for row in cur.fetchall()]
        conn = self._connect()
        try:
            cur = conn.execute("SELECT * FROM accounts ORDER BY username")
            return [self._row_to_account(row).to_dict() for row in cur.fetchall()]
        finally:
            conn.close()

    def create_user(
        self,
        username: str,
        password: str,
        full_name: str,
        roles: list[str],
        actor: str = "admin",
    ) -> UserAccount:
        """Administratively provision a new employee account with audit recording."""
        key = username.strip().lower()
        if not password or len(password) < 8:
            self.record_admin_audit(
                actor=actor,
                action="user_created",
                target=key or "unknown",
                details={"roles": roles, "full_name": full_name, "error": "Password must be at least 8 characters long"},
                outcome="denied",
            )
            raise ValueError("Password must be at least 8 characters long")
        p_hash, salt, iters = hash_password(password, iterations=self.iterations)
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute("SELECT username FROM accounts WHERE username = ?", (key,))
                if cur.fetchone():
                    with conn:
                        conn.execute(
                            "INSERT INTO admin_audit_events (actor, action, target, details, timestamp, outcome) VALUES (?, ?, ?, ?, ?, ?)",
                            (actor, "user_created", key, json.dumps({"roles": roles, "error": f"User '{username}' already exists"}), now_iso, "denied"),
                        )
                    raise ValueError(f"User '{username}' already exists")
                with conn:
                    conn.execute(
                        """
                        INSERT INTO accounts (username, full_name, password_hash, salt, roles, is_active, failed_login_attempts, locked_until, iterations, token_version, is_demo, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, 1, 0, 0.0, ?, 1, 0, ?, ?)
                        """,
                        (key, full_name.strip(), p_hash, salt, json.dumps(list(roles)), iters, now_iso, now_iso),
                    )
                    user_details: dict[str, Any] = {"roles": roles, "full_name": full_name}
                    if "host_operator:" in actor:
                        for part in actor.split("|"):
                            if ":" in part:
                                k, v = part.split(":", 1)
                                if k == "host_operator":
                                    user_details["operator"] = v
                                elif k == "ticket":
                                    user_details["ticket"] = v
                                elif k == "approval":
                                    user_details["approval_ref"] = v
                    conn.execute(
                        "INSERT INTO admin_audit_events (actor, action, target, details, timestamp, outcome) VALUES (?, ?, ?, ?, ?, ?)",
                        (actor, "user_created", key, json.dumps(user_details), now_iso, "allowed"),
                    )
                    return UserAccount(
                        username=key,
                        full_name=full_name.strip(),
                        password_hash=p_hash,
                        salt=salt,
                        roles=list(roles),
                        is_active=True,
                        iterations=iters,
                        token_version=1,
                        is_demo=False,
                        created_at=now_iso,
                        updated_at=now_iso,
                    )
            finally:
                if self._memory_conn is None:
                    conn.close()

    def provision_privileged_admin(
        self,
        username: str,
        password: str,
        ticket: str,
        approval_ref: str,
        operator: str,
        full_name: str | None = None,
        independent_approver: str | None = None,
        manual_attestation: bool = False,
        itsm_url: str | None = None,
        itsm_token: str | None = None,
        itsm_client: Any = None,
        operator_verifier: Any = None,
        authorized_approvers: set[str] | frozenset[str] | None = None,
        config_path: str | Path | None = None,
        is_production: bool | None = None,
    ) -> UserAccount:
        """Administratively provision a privileged administrator with verified approval and audit attribution.

        Invariants enforced:
        1. Clean account identifiers: Ticket and approval references are stored strictly as structured
           audit metadata in admin_audit_events; account identifiers (username and full_name) are NOT altered
           to encode approval evidence.
        2. Audit storage failure fail-closed invariant: User creation and audit event recording execute
           within a single atomic database transaction. Any audit storage failure rolls back account creation,
           ensuring an audit storage failure cannot silently permit privileged account creation.
        3. Sensitive credential exclusion: Plaintext passwords, password hashes, salts, and tokens are
           never recorded in audit logs.
        4. Structured audit metadata linking: The approved ticket, target_system, approval reference,
           operator, and independent approver are linked in structured audit metadata.
        """
        target_account = username.strip().lower() if username else "unknown"
        clean_full_name = full_name.strip() if full_name and full_name.strip() else "Staging Administrator"
        op_label = operator.strip() if operator and operator.strip() else "unverified"
        appr_label = independent_approver.strip() if independent_approver and independent_approver.strip() else "unverified"
        tk_label = ticket.strip() if ticket and ticket.strip() else "none"
        ref_label = approval_ref.strip() if approval_ref and approval_ref.strip() else "unverified"
        actor_label = f"host_operator:{op_label}|approver:{appr_label}|ticket:{tk_label}|approval:{ref_label}"

        try:
            verification = verify_change_approval(
                ticket=ticket,
                approval_ref=approval_ref,
                operator=operator,
                independent_approver=independent_approver,
                authorized_approvers=authorized_approvers,
                itsm_url=itsm_url,
                itsm_token=itsm_token,
                itsm_client=itsm_client,
                manual_attestation=manual_attestation,
                operator_verifier=operator_verifier,
                config_path=config_path,
                is_production=is_production,
            )
        except Exception as e:
            err_msg = str(e)
            self.record_admin_audit(
                actor=actor_label,
                action="privileged_admin_provision",
                target=target_account,
                details={
                    "error": err_msg,
                    "ticket": ticket,
                    "target_system": "intranet-assistant",
                    "approval_ref": approval_ref,
                    "operator": operator,
                    "independent_approver": independent_approver or "none",
                    "role": "admin",
                },
                outcome="denied",
            )
            raise ValueError(err_msg) from e

        if not password or len(password) < 8:
            err_msg = "Password must be at least 8 characters long"
            self.record_admin_audit(
                actor=actor_label,
                action="privileged_admin_provision",
                target=target_account,
                details={
                    "error": err_msg,
                    "ticket": ticket,
                    "target_system": verification.get("target_system", "intranet-assistant"),
                    "approval_ref": approval_ref,
                    "operator": operator,
                    "independent_approver": independent_approver or "none",
                    "role": "admin",
                },
                outcome="denied",
            )
            raise ValueError(err_msg)

        verified_approval_ref = verification["approval_ref"]
        resolved_approver = verification.get("independent_approver", independent_approver or "itsm_authorized")
        actor_label = f"host_operator:{operator}|approver:{resolved_approver}|ticket:{ticket}|approval:{verified_approval_ref}"

        p_hash, salt, iters = hash_password(password, iterations=self.iterations)
        now_iso = datetime.now(timezone.utc).isoformat()

        audit_details: dict[str, Any] = {
            "roles": ["admin"],
            "ticket": ticket,
            "target_system": verification.get("target_system", "intranet-assistant"),
            "approval_ref": verified_approval_ref,
            "operator": operator,
            "independent_approver": resolved_approver,
            "verification_method": verification["method"],
            "status": verification["status"],
        }

        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute("SELECT username FROM accounts WHERE username = ?", (target_account,))
                if cur.fetchone():
                    err_msg = f"User '{target_account}' already exists"
                    with conn:
                        conn.execute(
                            "INSERT INTO admin_audit_events (actor, action, target, details, timestamp, outcome) VALUES (?, ?, ?, ?, ?, ?)",
                            (actor_label, "privileged_admin_provision", target_account, json.dumps({
                                "error": err_msg,
                                "ticket": ticket,
                                "target_system": verification.get("target_system", "intranet-assistant"),
                                "approval_ref": verified_approval_ref,
                                "operator": operator,
                                "independent_approver": resolved_approver,
                                "role": "admin",
                            }), now_iso, "denied"),
                        )
                    raise ValueError(err_msg)

                # Atomic execution: account insertion AND audit event recording execute in a single transaction
                with conn:
                    conn.execute(
                        """
                        INSERT INTO accounts (username, full_name, password_hash, salt, roles, is_active, failed_login_attempts, locked_until, iterations, token_version, is_demo, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, 1, 0, 0.0, ?, 1, 0, ?, ?)
                        """,
                        (target_account, clean_full_name, p_hash, salt, json.dumps(["admin"]), iters, now_iso, now_iso),
                    )
                    conn.execute(
                        "INSERT INTO admin_audit_events (actor, action, target, details, timestamp, outcome) VALUES (?, ?, ?, ?, ?, ?)",
                        (actor_label, "privileged_admin_provision", target_account, json.dumps(audit_details), now_iso, "allowed"),
                    )

                return UserAccount(
                    username=target_account,
                    full_name=clean_full_name,
                    password_hash=p_hash,
                    salt=salt,
                    roles=["admin"],
                    is_active=True,
                    iterations=iters,
                    token_version=1,
                    is_demo=False,
                    created_at=now_iso,
                    updated_at=now_iso,
                )
            except Exception as e:
                # If transaction failed (e.g. audit failure, DB write error), transaction rolled back; user is NOT created
                raise
            finally:
                if self._memory_conn is None:
                    conn.close()

    def update_roles(self, username: str, roles: list[str], actor: str = "admin") -> bool:
        """Administratively update user roles; immediately effective on subsequent requests."""
        key = username.strip().lower()
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    cur = conn.execute("SELECT username FROM accounts WHERE username = ?", (key,))
                    if not cur.fetchone():
                        return False
                    conn.execute(
                        "UPDATE accounts SET roles = ?, updated_at = ? WHERE username = ?",
                        (json.dumps(list(roles)), now_iso, key),
                    )
                    conn.execute(
                        "INSERT INTO admin_audit_events (actor, action, target, details, timestamp, outcome) VALUES (?, ?, ?, ?, ?, ?)",
                        (actor, "role_updated", key, json.dumps({"roles": roles}), now_iso, "allowed"),
                    )
                    return True
            finally:
                if self._memory_conn is None:
                    conn.close()

    def set_active_status(self, username: str, is_active: bool, actor: str = "admin") -> bool:
        """Administratively activate or deactivate an account (immediate revocation)."""
        key = username.strip().lower()
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    cur = conn.execute("SELECT username FROM accounts WHERE username = ?", (key,))
                    if not cur.fetchone():
                        return False
                    conn.execute(
                        "UPDATE accounts SET is_active = ?, updated_at = ? WHERE username = ?",
                        (1 if is_active else 0, now_iso, key),
                    )
                    conn.execute(
                        "INSERT INTO admin_audit_events (actor, action, target, details, timestamp, outcome) VALUES (?, ?, ?, ?, ?, ?)",
                        (actor, "status_changed", key, json.dumps({"is_active": is_active}), now_iso, "allowed"),
                    )
                    return True
            finally:
                if self._memory_conn is None:
                    conn.close()

    def reset_password(self, username: str, new_password: str, actor: str = "admin") -> bool:
        """Administratively reset password, reset lockout, and invalidate existing sessions."""
        key = username.strip().lower()
        if len(new_password) < 8:
            raise ValueError("Password must be at least 8 characters long")
        p_hash, salt, iters = hash_password(new_password, iterations=self.iterations)
        now_iso = datetime.now(timezone.utc).isoformat()
        now_ts = time.time()
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    cur = conn.execute("SELECT username FROM accounts WHERE username = ?", (key,))
                    if not cur.fetchone():
                        return False
                    conn.execute(
                        "UPDATE accounts SET password_hash = ?, salt = ?, iterations = ?, failed_login_attempts = 0, locked_until = 0.0, token_version = token_version + 1, updated_at = ? WHERE username = ?",
                        (p_hash, salt, iters, now_iso, key),
                    )
                    conn.execute(
                        "INSERT INTO admin_audit_events (actor, action, target, details, timestamp, outcome) VALUES (?, ?, ?, ?, ?, ?)",
                        (actor, "password_reset", key, json.dumps({"reason": "admin_reset"}), now_iso, "allowed"),
                    )
                    return True
            finally:
                if self._memory_conn is None:
                    conn.close()

    def revoke(self, jti: str, subject: str = "", expires_at: float = 0.0) -> None:
        """Persist a revoked session ID (jti) in SQLite."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO session_revocations (jti, subject, revoked_at, expires_at) VALUES (?, ?, ?, ?)",
                        (jti, subject, now_iso, expires_at),
                    )
            finally:
                if self._memory_conn is None:
                    conn.close()

    def is_revoked(self, jti: str, subject: str = "") -> bool:
        """Check whether a session token is revoked."""
        if self._memory_conn is not None:
            with self._lock:
                cur = self._memory_conn.execute("SELECT 1 FROM session_revocations WHERE jti = ?", (jti,))
                return cur.fetchone() is not None
        conn = self._connect()
        try:
            cur = conn.execute("SELECT 1 FROM session_revocations WHERE jti = ?", (jti,))
            return cur.fetchone() is not None
        finally:
            conn.close()

    def prune_expired(self) -> int:
        """Prune expired session revocations whose JWT expiration time has passed."""
        now = time.time()
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    cur = conn.execute(
                        "DELETE FROM session_revocations WHERE expires_at > 0 AND expires_at < ?",
                        (now,),
                    )
                    return cur.rowcount
            finally:
                if self._memory_conn is None:
                    conn.close()

    def clear(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    conn.execute("DELETE FROM session_revocations")
            finally:
                if self._memory_conn is None:
                    conn.close()

    def record_admin_audit(
        self,
        actor: str,
        action: str,
        target: str,
        details: dict[str, object] | None = None,
        outcome: str = "allowed",
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._connect()
            try:
                with conn:
                    conn.execute(
                        "INSERT INTO admin_audit_events (actor, action, target, details, timestamp, outcome) VALUES (?, ?, ?, ?, ?, ?)",
                        (actor, action, target, json.dumps(details or {}), now_iso, outcome),
                    )
            finally:
                if self._memory_conn is None:
                    conn.close()

    def list_admin_audit_events(self, limit: int = 50) -> list[dict[str, object]]:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    "SELECT id, actor, action, target, details, timestamp, outcome FROM admin_audit_events ORDER BY id DESC LIMIT ?",
                    (limit,),
                )
                events = []
                for row in cur.fetchall():
                    try:
                        det = json.loads(row["details"])
                    except Exception:
                        det = {}
                    events.append(
                        {
                            "id": row["id"],
                            "actor": row["actor"],
                            "action": row["action"],
                            "target": row["target"],
                            "details": det,
                            "timestamp": row["timestamp"],
                            "outcome": row["outcome"],
                        }
                    )
                return events
            finally:
                if self._memory_conn is None:
                    conn.close()

    def backup(self, destination_path: str | Path) -> None:
        """Online hot backup of the SQLite database without interrupting active readers/writers."""
        dest_path = str(destination_path)
        with self._lock:
            src = self._connect()
            try:
                dest = sqlite3.connect(dest_path)
                try:
                    src.backup(dest)
                finally:
                    dest.close()
            finally:
                if self._memory_conn is None:
                    src.close()


# Backward-compatible aliases and wrappers
class AccountStore(SqliteAuthStore):
    """Durable SQLite account store matching the AccountStore interface."""

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        is_production: bool = False,
        iterations: int = DEFAULT_ITERATIONS,
        demo_accounts: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(db_path=db_path, is_production=is_production, iterations=iterations, demo_accounts=demo_accounts)


class SessionRevocationStore(SqliteAuthStore):
    """Durable SQLite session revocation store matching the SessionRevocationStore interface."""

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        is_production: bool = False,
        iterations: int = DEFAULT_ITERATIONS,
        demo_accounts: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(db_path=db_path, is_production=is_production, iterations=iterations, demo_accounts=demo_accounts)


__all__ = [
    "AUTHORIZED_OPERATOR_GROUPS",
    "DEFAULT_DEV_DEMO_ACCOUNTS",
    "DEFAULT_ITERATIONS",
    "LOCKOUT_ATTEMPTS",
    "LOCKOUT_DURATION_SECONDS",
    "UserAccount",
    "hash_password",
    "verify_password",
    "validate_ticket_format",
    "validate_approval_reference_format",
    "resolve_trusted_operator_identity",
    "verify_change_approval",
    "SqliteAuthStore",
    "AccountStore",
    "SessionRevocationStore",
]
