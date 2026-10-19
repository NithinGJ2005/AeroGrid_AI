"""Tests for staging account provisioning, credential encoding, WAL rollback, and preflight verification."""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from app.auth.accounts import SqliteAuthStore


def test_account_provisioning_with_complex_passwords_and_special_chars():
    """Verify that SqliteAuthStore safely provisions and authenticates accounts with quotes, backslashes, and special characters."""
    test_passwords = [
        r'P@ss\"word\With\"Quotes\'And\\Backslashes!',
        r'Complex\"\"Key\\//::;;$$``^^&&**(())',
        r"NormalSecret12345!",
        'Password with spaces and "double quotes" and \\backslash\\',
        'Special`$!@#%^&*()_+-=[]{}|;:",.<>?/~',
    ]

    for idx, password in enumerate(test_passwords, start=1):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "test_auth.sqlite3"
            store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)

            username = f"user_{idx}"
            role = "engineer"
            role_label = role.capitalize()
            full_name = f"Staging {role_label}"

            # Stream via JSON (simulating getpass + json.dump / json.load)
            payload = json.dumps({"username": username, "password": password, "role": role})
            creds = json.loads(payload)

            username = creds["username"]
            password = creds["password"]
            role = creds["role"]
            role_label = role.capitalize()
            full_name = f"Staging {role_label}"

            user = store.create_user(
                username=username,
                password=password,
                full_name=full_name,
                roles=[role],
            )
            assert user.username == username
            assert user.roles == ["engineer"]
            assert user.full_name == "Staging Engineer"

            # Authenticate with candidate password
            auth_user = store.authenticate(username, password)
            assert auth_user is not None, f"Failed to authenticate user {username} with complex password!"
            assert auth_user.roles == ["engineer"]

            # Wrong password rejected
            assert store.authenticate(username, password + "_wrong") is None


def test_exact_provisioning_stdin_pipeline():
    """Verify the exact stdin streaming pipeline between producer and consumer scripts against a disposable DB across Python runtimes."""
    interpreters = [sys.executable]
    py311_candidate = Path(r"C:\Users\Chinmayi G J\AppData\Roaming\uv\python\cpython-3.11-windows-x86_64-none\python.exe")
    if py311_candidate.exists() and str(py311_candidate) not in interpreters:
        interpreters.append(str(py311_candidate))

    repo_root = Path(__file__).resolve().parents[2]
    site_packages = repo_root / ".venv" / "Lib" / "site-packages"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{repo_root};{site_packages}"

    for python_bin in interpreters:
        with tempfile.TemporaryDirectory() as td:
            db_path = str(Path(td) / "auth.sqlite3")

            consumer_code = f"""
import json, sys
from app.auth.accounts import SqliteAuthStore

creds = json.load(sys.stdin)
username = creds["username"].strip()
password = creds["password"]
role = creds["role"].strip().lower()

# Role validation before create_user
ALLOWED_TEST_ROLES = {{"employee", "engineer", "hr", "analyst"}}
if role == "admin":
    sys.exit("ERROR: Accidental admin provisioning prevented.")
if role not in ALLOWED_TEST_ROLES:
    allowed_str = ", ".join(sorted(ALLOWED_TEST_ROLES))
    sys.exit(f"ERROR: Unsupported role \\"{{role}}\\". Permitted staging test roles are: {{allowed_str}}")

role_label = role.capitalize()
full_name = f"Staging {{role_label}}"

store = SqliteAuthStore(db_path=r"{db_path}", is_production=True, iterations=1000)
store.create_user(username=username, password=password, full_name=full_name, roles=[role])
print(f"Provisioned temporary staging user: {{username}} with role: {{role}}")
"""

            complex_pw = r'Str0ng\"P@ss\\w0rd!#%&'
            producer_code = f"""
import json, sys
payload = {{
    "username": "staging_test_user",
    "password": {json.dumps(complex_pw)},
    "role": "engineer"
}}
json.dump(payload, sys.stdout)
"""

            p1 = subprocess.Popen([python_bin, "-c", producer_code], stdout=subprocess.PIPE, env=env)
            p2 = subprocess.Popen(
                [python_bin, "-c", consumer_code],
                stdin=p1.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            p1.stdout.close()
            out, err = p2.communicate()

            assert p2.returncode == 0, f"Consumer failed on {python_bin}: {err}"
            assert "Provisioned temporary staging user: staging_test_user with role: engineer" in out

            # Verify authentication against disposable database
            verify_store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)
            auth_user = verify_store.authenticate("staging_test_user", complex_pw)
            assert auth_user is not None
            assert auth_user.roles == ["engineer"]
            assert verify_store.authenticate("staging_test_user", "IncorrectPassword123!") is None


def test_ordinary_provisioning_rejects_admin_and_unsupported_roles():
    """Verify that ordinary test-account provisioning strictly rejects 'admin' and unsupported roles before calling create_user, auditing all failures."""
    repo_root = Path(__file__).resolve().parents[2]
    site_packages = repo_root / ".venv" / "Lib" / "site-packages"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{repo_root};{site_packages}"

    consumer_template = """
import json, sys
from app.auth.accounts import SqliteAuthStore

creds = json.load(sys.stdin)
username = creds["username"].strip()
password = creds["password"]
role = creds["role"].strip().lower()

# Server-side role validation before invoking account store
ALLOWED_TEST_ROLES = {"employee", "engineer", "hr", "analyst"}
if role == "admin":
    store = SqliteAuthStore(db_path=DB_PATH, is_production=True, iterations=1000)
    store.record_admin_audit(
        actor="ordinary_staging_provisioning",
        action="user_created",
        target=username if username else "unknown",
        details={"role": role, "error": "Accidental admin provisioning rejected in ordinary flow"},
        outcome="denied",
    )
    sys.exit("ERROR: Accidental admin provisioning prevented. The \\"admin\\" role cannot be assigned through ordinary staging test-account provisioning. Refer to Section 5.1.1 for privileged administrator provisioning.")
if role not in ALLOWED_TEST_ROLES:
    store = SqliteAuthStore(db_path=DB_PATH, is_production=True, iterations=1000)
    store.record_admin_audit(
        actor="ordinary_staging_provisioning",
        action="user_created",
        target=username if username else "unknown",
        details={"role": role, "error": f"Unsupported role {role}"},
        outcome="denied",
    )
    allowed_str = ", ".join(sorted(ALLOWED_TEST_ROLES))
    sys.exit(f"ERROR: Unsupported role \\"{role}\\". Permitted staging test roles are: {allowed_str}")

store = SqliteAuthStore(db_path=DB_PATH, is_production=True, iterations=1000)
store.create_user(username=username, password=password, full_name=f"Staging {role.capitalize()}", roles=[role])
print(f"Provisioned temporary staging user: {username} with role: {role}")
"""

    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "auth.sqlite3")
        consumer_code = consumer_template.replace("DB_PATH", repr(db_path))

        # 1. Reject 'admin' in ordinary flow
        p1 = subprocess.Popen(
            [sys.executable, "-c", 'import json, sys; json.dump({"username": "rogue_admin", "password": "Password123!", "role": "admin"}, sys.stdout)'],
            stdout=subprocess.PIPE,
            env=env,
        )
        p2 = subprocess.Popen([sys.executable, "-c", consumer_code], stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        p1.stdout.close()
        out, err = p2.communicate()
        assert p2.returncode != 0
        assert "Accidental admin provisioning prevented" in err

        # Verify rogue_admin was not created but was recorded as denied in audit log
        store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)
        assert store.get_user("rogue_admin") is None
        audit_events = store.list_admin_audit_events()
        assert any(e["target"] == "rogue_admin" and e["outcome"] == "denied" for e in audit_events)

        # 2. Reject unsupported roles
        for bad_role in ["superuser", "root", "unknown_role"]:
            p1 = subprocess.Popen(
                [sys.executable, "-c", f'import json, sys; json.dump({{"username": "test_{bad_role}", "password": "Password123!", "role": "{bad_role}"}}, sys.stdout)'],
                stdout=subprocess.PIPE,
                env=env,
            )
            p2 = subprocess.Popen([sys.executable, "-c", consumer_code], stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
            p1.stdout.close()
            out, err = p2.communicate()
            assert p2.returncode != 0
            assert f"Unsupported role \"{bad_role}\"" in err

            audit_events = store.list_admin_audit_events()
            assert any(e["target"] == f"test_{bad_role}" and e["outcome"] == "denied" for e in audit_events)


def test_privileged_admin_provisioning_with_explicit_authorization():
    """Verify dedicated privileged administrator account provisioning with ticket approval verification, operator audit attribution, and audit failure recording."""
    repo_root = Path(__file__).resolve().parents[2]
    site_packages = repo_root / ".venv" / "Lib" / "site-packages"
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{repo_root};{site_packages}"

    privileged_consumer = r"""
import json, os, sys
from app.auth.accounts import SqliteAuthStore

store = SqliteAuthStore(db_path=DB_PATH, is_production=True, iterations=1000)

try:
    creds = json.load(sys.stdin)
except Exception as e:
    store.record_admin_audit(
        actor="unknown",
        action="privileged_admin_provision",
        target="unknown",
        details={"error": f"Malformed provisioning payload: {e}"},
        outcome="denied",
    )
    sys.exit("ERROR: Malformed provisioning payload.")

username = creds.get("username", "").strip()
password = creds.get("password", "")
role = creds.get("role", "").strip().lower()
ticket = creds.get("ticket", "").strip()
approval_ref = creds.get("approval_ref", "").strip()
operator = creds.get("operator", "").strip()
independent_approver = creds.get("independent_approver", "").strip()
manual_attestation = bool(creds.get("manual_attestation", False))

if role != "admin":
    target_account = username if username else "unknown"
    op_label = operator if operator else "unverified"
    appr_label = independent_approver if independent_approver else "unverified"
    tk_label = ticket if ticket else "none"
    ref_label = approval_ref if approval_ref else "unverified"
    store.record_admin_audit(
        actor=f"host_operator:{op_label}|approver:{appr_label}|ticket:{tk_label}|approval:{ref_label}",
        action="privileged_admin_provision",
        target=target_account,
        details={"error": "Role must be explicitly authorized admin", "role": role},
        outcome="denied",
    )
    sys.exit("ERROR: Privileged provisioning only accepts the explicitly authorized admin role.")

try:
    account = store.provision_privileged_admin(
        username=username,
        password=password,
        ticket=ticket,
        approval_ref=approval_ref,
        operator=operator,
        independent_approver=independent_approver,
        manual_attestation=manual_attestation,
        itsm_url=os.environ.get("ITSM_API_URL"),
        itsm_token=os.environ.get("ITSM_API_TOKEN"),
    )
    print(f"Provisioned authorized privileged administrator: {account.username} by operator: {operator} (Ticket: {ticket}, Approver: {independent_approver}, Approval: {approval_ref})")
except Exception as e:
    sys.exit(f"ERROR: Failed to provision privileged administrator: {e}")
"""

    with tempfile.TemporaryDirectory() as td:
        db_path = str(Path(td) / "auth.sqlite3")
        consumer_code = privileged_consumer.replace("DB_PATH", repr(db_path))

        # 1. Successful provisioning with valid ticket, approval reference, independent approver, and verified host operator
        p1 = subprocess.Popen(
            [sys.executable, "-c", 'import json, sys; json.dump({"username": "stage_adm", "password": "AdminPassword123!", "role": "admin", "ticket": "CHG-20261017-001", "approval_ref": "CAB-APP-202610-092", "operator": "sec_ops_alice", "independent_approver": "cab_chair_morris", "manual_attestation": True}, sys.stdout)'],
            stdout=subprocess.PIPE,
            env=env,
        )
        p2 = subprocess.Popen([sys.executable, "-c", consumer_code], stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        p1.stdout.close()
        out, err = p2.communicate()
        assert p2.returncode == 0, f"Privileged admin failed: {err}"
        assert "Provisioned authorized privileged administrator: stage_adm by operator: sec_ops_alice (Ticket: CHG-20261017-001, Approver: cab_chair_morris, Approval: CAB-APP-202610-092)" in out

        # Verify admin in database and audit log
        store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)
        admin_account = store.authenticate("stage_adm", "AdminPassword123!")
        assert admin_account is not None
        assert admin_account.roles == ["admin"]
        # Account identifiers must NOT be altered to encode ticket/operator approval evidence
        assert admin_account.full_name == "Staging Administrator"
        assert admin_account.username == "stage_adm"

        # Verify audit trail contains composite operator, independent approver, ticket, and approval attribution with allowed outcome
        audit_events = store.list_admin_audit_events()
        allowed_admin_event = next(e for e in audit_events if e["target"] == "stage_adm" and e["outcome"] == "allowed")
        assert "host_operator:sec_ops_alice" in allowed_admin_event["actor"]
        assert "approver:cab_chair_morris" in allowed_admin_event["actor"]
        assert "ticket:CHG-20261017-001" in allowed_admin_event["actor"]
        assert "approval:CAB-APP-202610-092" in allowed_admin_event["actor"]
        assert allowed_admin_event["action"] == "privileged_admin_provision"
        assert allowed_admin_event["timestamp"] != ""
        assert allowed_admin_event["details"]["ticket"] == "CHG-20261017-001"
        assert allowed_admin_event["details"]["operator"] == "sec_ops_alice"
        assert allowed_admin_event["details"]["independent_approver"] == "cab_chair_morris"
        assert allowed_admin_event["details"]["approval_ref"] == "CAB-APP-202610-092"

        # 2. Rejection of invalid ticket format (audited as denied)
        p1 = subprocess.Popen(
            [sys.executable, "-c", 'import json, sys; json.dump({"username": "stage_adm2", "password": "AdminPassword123!", "role": "admin", "ticket": "invalid_ticket_no_prefix", "approval_ref": "CAB-APP-001", "operator": "sec_ops_alice", "independent_approver": "cab_chair_morris", "manual_attestation": True}, sys.stdout)'],
            stdout=subprocess.PIPE,
            env=env,
        )
        p2 = subprocess.Popen([sys.executable, "-c", consumer_code], stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        p1.stdout.close()
        out, err = p2.communicate()
        assert p2.returncode != 0
        assert "Ticket must match organizational format" in err or "Invalid ticket format" in err or "Missing or invalid organizational change authorization ticket" in err
        events = store.list_admin_audit_events()
        assert any(e["target"] == "stage_adm2" and e["outcome"] == "denied" for e in events)

        # 3. Rejection of unapproved ticket (format valid, but approval missing or empty)
        p1 = subprocess.Popen(
            [sys.executable, "-c", 'import json, sys; json.dump({"username": "stage_adm3", "password": "AdminPassword123!", "role": "admin", "ticket": "CHG-20261017-002", "approval_ref": "", "operator": "sec_ops_alice", "independent_approver": "cab_chair_morris", "manual_attestation": True}, sys.stdout)'],
            stdout=subprocess.PIPE,
            env=env,
        )
        p2 = subprocess.Popen([sys.executable, "-c", consumer_code], stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        p1.stdout.close()
        out, err = p2.communicate()
        assert p2.returncode != 0
        assert "verified ticket approval" in err or "Missing approval evidence" in err
        events = store.list_admin_audit_events()
        assert any(e["target"] == "stage_adm3" and e["outcome"] == "denied" for e in events)

        # 4. Rejection of missing / untrusted operator identity
        p1 = subprocess.Popen(
            [sys.executable, "-c", 'import json, sys; json.dump({"username": "stage_adm4", "password": "AdminPassword123!", "role": "admin", "ticket": "SEC-2026-ADM-01", "approval_ref": "CAB-APP-001", "operator": "", "independent_approver": "cab_chair_morris", "manual_attestation": True}, sys.stdout)'],
            stdout=subprocess.PIPE,
            env=env,
        )
        p2 = subprocess.Popen([sys.executable, "-c", consumer_code], stdin=p1.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        p1.stdout.close()
        out, err = p2.communicate()
        assert p2.returncode != 0
        assert "Missing host operator identity" in err or "Missing or unauthorized host operator identity" in err
        events = store.list_admin_audit_events()
        assert any(e["target"] == "stage_adm4" and e["outcome"] == "denied" for e in events)


def test_privileged_admin_provisioning_approved_itsm_scenario():
    """Verify privileged administrator provisioning with an approved ITSM integration and complete audit attribution."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "auth.sqlite3"
        store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)

        mock_itsm = lambda t: {
            "status": "APPROVED",
            "approval_id": "CAB-APP-202610-092",
            "target_system": "intranet-assistant",
            "approver": "cab_chair_morris",
        }

        account = store.provision_privileged_admin(
            username="stage_adm_itsm",
            password="AdminPassword123!",
            ticket="SEC-2026-ADM-01",
            approval_ref="CAB-APP-202610-092",
            operator="secops_operator",
            itsm_client=mock_itsm,
        )

        assert account is not None
        assert account.username == "stage_adm_itsm"
        assert account.roles == ["admin"]

        audit_events = store.list_admin_audit_events()
        allowed_events = [e for e in audit_events if e["target"] == "stage_adm_itsm" and e["outcome"] == "allowed"]
        assert len(allowed_events) >= 1
        priv_event = next(e for e in allowed_events if e["action"] == "privileged_admin_provision")
        assert "host_operator:secops_operator" in priv_event["actor"]
        assert "ticket:SEC-2026-ADM-01" in priv_event["actor"]
        assert "approval:CAB-APP-202610-092" in priv_event["actor"]
        assert priv_event["target"] == "stage_adm_itsm"
        assert priv_event["action"] == "privileged_admin_provision"
        assert priv_event["timestamp"] != ""
        assert priv_event["outcome"] == "allowed"
        assert priv_event["details"]["operator"] == "secops_operator"
        assert priv_event["details"]["ticket"] == "SEC-2026-ADM-01"
        assert priv_event["details"]["approval_ref"] == "CAB-APP-202610-092"


def test_privileged_admin_provisioning_rejected_and_cancelled_itsm_scenarios():
    """Verify that privileged administrator provisioning is rejected when change ticket is rejected or cancelled in ITSM."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "auth.sqlite3"
        store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)

        # 1. Rejected ticket in ITSM
        mock_rejected = lambda t: {
            "status": "REJECTED",
            "approval_id": "CAB-APP-202610-092",
            "target_system": "intranet-assistant",
        }
        with pytest.raises(ValueError, match="rejected in ITSM"):
            store.provision_privileged_admin(
                username="rejected_admin",
                password="AdminPassword123!",
                ticket="SEC-2026-ADM-02",
                approval_ref="CAB-APP-202610-092",
                operator="secops_operator",
                itsm_client=mock_rejected,
            )
        assert store.get_user("rejected_admin") is None
        events = store.list_admin_audit_events()
        rej_event = next(e for e in events if e["target"] == "rejected_admin")
        assert rej_event["outcome"] == "denied"
        assert "rejected in ITSM" in rej_event["details"]["error"]

        # 2. Cancelled ticket in ITSM
        mock_cancelled = lambda t: {
            "status": "CANCELLED",
            "approval_id": "CAB-APP-202610-092",
            "target_system": "intranet-assistant",
        }
        with pytest.raises(ValueError, match="rejected in ITSM"):
            store.provision_privileged_admin(
                username="cancelled_admin",
                password="AdminPassword123!",
                ticket="CHG-20261017-005",
                approval_ref="CAB-APP-202610-092",
                operator="secops_operator",
                itsm_client=mock_cancelled,
            )
        assert store.get_user("cancelled_admin") is None
        events = store.list_admin_audit_events()
        canc_event = next(e for e in events if e["target"] == "cancelled_admin")
        assert canc_event["outcome"] == "denied"


def test_privileged_admin_provisioning_nonexistent_itsm_ticket_scenario():
    """Verify that privileged provisioning fails when the ticket does not exist in ITSM (nonexistent ticket / 404)."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "auth.sqlite3"
        store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)

        mock_nonexistent = lambda t: None
        with pytest.raises(ValueError, match="does not exist in ITSM"):
            store.provision_privileged_admin(
                username="ghost_admin",
                password="AdminPassword123!",
                ticket="OPS-2026-999-999",
                approval_ref="CAB-APP-202610-092",
                operator="secops_operator",
                itsm_client=mock_nonexistent,
            )
        assert store.get_user("ghost_admin") is None
        events = store.list_admin_audit_events()
        ghost_event = next(e for e in events if e["target"] == "ghost_admin")
        assert ghost_event["outcome"] == "denied"
        assert "does not exist in ITSM" in ghost_event["details"]["error"]


def test_privileged_admin_provisioning_missing_ticket_scenario():
    """Verify that privileged provisioning fails when change ticket is missing or empty."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "auth.sqlite3"
        store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)

        with pytest.raises(ValueError, match="Missing change ticket"):
            store.provision_privileged_admin(
                username="missing_ticket_admin",
                password="AdminPassword123!",
                ticket="",
                approval_ref="CAB-APP-202610-092",
                operator="secops_operator",
                manual_attestation=True,
            )
        assert store.get_user("missing_ticket_admin") is None
        events = store.list_admin_audit_events()
        miss_event = next(e for e in events if e["target"] == "missing_ticket_admin")
        assert miss_event["outcome"] == "denied"
        assert "Missing change ticket" in miss_event["details"]["error"]


def test_privileged_admin_provisioning_arbitrary_approval_reference_strictly_rejected():
    """Verify that privileged provisioning cannot proceed merely because a syntactically valid ticket and arbitrary approval-reference string were supplied."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "auth.sqlite3"
        store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)

        arbitrary_references = [
            "arbitrary_string",
            "foobar123",
            "12345",
            "approved",
            "arbitrary-reference-grant-access",
            "trust-me-im-an-admin",
            "yes",
        ]

        # 1. Manual mode: arbitrary approval reference strings are strictly rejected
        for bad_ref in arbitrary_references:
            target_user = f"user_{bad_ref[:6]}"
            with pytest.raises(ValueError, match="Inadequate approval evidence"):
                store.provision_privileged_admin(
                    username=target_user,
                    password="AdminPassword123!",
                    ticket="CHG-20261017-001",
                    approval_ref=bad_ref,
                    operator="secops_operator",
                    independent_approver="cab_chair_morris",
                    manual_attestation=True,
                )
            assert store.get_user(target_user) is None
            events = store.list_admin_audit_events()
            bad_event = next(e for e in events if e["target"] == target_user and e["outcome"] == "denied")
            assert "Inadequate approval evidence" in bad_event["details"]["error"]

        # 2. ITSM mode: approval reference string that contradicts ITSM approval record is rejected
        mock_itsm = lambda t: {
            "status": "APPROVED",
            "approval_id": "CAB-APP-202610-092",
            "target_system": "intranet-assistant",
        }
        with pytest.raises(ValueError, match="does not match ITSM record approval ID"):
            store.provision_privileged_admin(
                username="mismatched_admin",
                password="AdminPassword123!",
                ticket="CHG-20261017-001",
                approval_ref="CAB-APP-202610-999",
                operator="secops_operator",
                itsm_client=mock_itsm,
            )
        assert store.get_user("mismatched_admin") is None
        events = store.list_admin_audit_events()
        mismatch_event = next(e for e in events if e["target"] == "mismatched_admin" and e["outcome"] == "denied")
        assert "does not match ITSM record approval ID" in mismatch_event["details"]["error"]


def test_privileged_admin_provisioning_manual_operator_attestation_enforced():
    """Verify that manual air-gapped staging provisioning requires explicit operator attestation of portal verification."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "auth.sqlite3"
        store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)

        # Attempt provisioning with valid ticket and CAB ref, but manual_attestation=False
        with pytest.raises(ValueError, match="Manual approval verification required"):
            store.provision_privileged_admin(
                username="unattested_admin",
                password="AdminPassword123!",
                ticket="CHG-20261017-001",
                approval_ref="CAB-APP-202610-092",
                operator="secops_operator",
                independent_approver="cab_chair_morris",
                manual_attestation=False,
            )
        assert store.get_user("unattested_admin") is None
        events = store.list_admin_audit_events()
        unattested_event = next(e for e in events if e["target"] == "unattested_admin")
        assert unattested_event["outcome"] == "denied"
        assert "Manual approval verification required" in unattested_event["details"]["error"]

        # Affirm manual attestation -> succeeds
        account = store.provision_privileged_admin(
            username="attested_admin",
            password="AdminPassword123!",
            ticket="CHG-20261017-001",
            approval_ref="CAB-APP-202610-092",
            operator="secops_operator",
            independent_approver="cab_chair_morris",
            manual_attestation=True,
        )
        assert account is not None
        assert account.username == "attested_admin"
        assert account.roles == ["admin"]


def test_privileged_admin_provisioning_target_system_mismatch_rejected():
    """Verify that an approved ITSM change ticket targeting a different system cannot be used for intranet-assistant."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "auth.sqlite3"
        store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)

        mock_wrong_system = lambda t: {
            "status": "APPROVED",
            "approval_id": "CAB-APP-202610-092",
            "target_system": "corporate-payroll-app",
        }
        with pytest.raises(ValueError, match="does not match 'intranet-assistant'"):
            store.provision_privileged_admin(
                username="wrong_sys_admin",
                password="AdminPassword123!",
                ticket="CHG-20261017-001",
                approval_ref="CAB-APP-202610-092",
                operator="secops_operator",
                itsm_client=mock_wrong_system,
            )
        assert store.get_user("wrong_sys_admin") is None
        events = store.list_admin_audit_events()
        wrong_sys_event = next(e for e in events if e["target"] == "wrong_sys_admin")
        assert wrong_sys_event["outcome"] == "denied"
        assert "does not match 'intranet-assistant'" in wrong_sys_event["details"]["error"]


def test_audit_records_capture_all_fields_and_integrity_boundary():
    """Verify that audit records capture operator, ticket, approval reference, target account, action, timestamp, and outcome without claiming non-repudiation."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "auth.sqlite3"
        store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)

        # 1. Allowed event
        store.provision_privileged_admin(
            username="audited_admin",
            password="AdminPassword123!",
            ticket="SEC-2026-ADM-01",
            approval_ref="CAB-APP-202610-092",
            operator="secops_operator",
            independent_approver="cab_chair_morris",
            manual_attestation=True,
        )

        # 2. Denied event
        try:
            store.provision_privileged_admin(
                username="denied_admin",
                password="AdminPassword123!",
                ticket="CHG-20261017-001",
                approval_ref="invalid_arbitrary_ref",
                operator="secops_operator",
                independent_approver="cab_chair_morris",
                manual_attestation=True,
            )
        except ValueError:
            pass

        events = store.list_admin_audit_events()
        assert len(events) >= 2

        for ev in events:
            # Check all required fields are present
            assert "actor" in ev
            assert "action" in ev
            assert "target" in ev
            assert "details" in ev
            assert "timestamp" in ev
            assert "outcome" in ev
            assert ev["outcome"] in ("allowed", "denied")

            # Check attribution captures operator, ticket, approval_ref
            actor = ev["actor"]
            assert "host_operator:" in actor
            assert "ticket:" in actor
            assert "approval:" in actor

            details = ev["details"]
            assert "operator" in details
            assert "ticket" in details
            assert "approval_ref" in details
            assert "independent_approver" in details


def test_runbook_commands_and_python311_syntax_consistency():
    """Verify that all Python commands in docs/STAGING_RUNBOOK.md are valid AST and all Compose commands are standardized."""
    import ast
    import re

    repo_root = Path(__file__).resolve().parents[2]
    runbook_path = repo_root / "docs" / "STAGING_RUNBOOK.md"
    content = runbook_path.read_text(encoding="utf-8")

    # 1. Parse all single-quoted python3 -c '...' blocks
    blocks = re.findall(r"python3 -c '([^']*)'", content)
    assert len(blocks) >= 4, f"Expected at least 4 python3 -c blocks, found {len(blocks)}"
    for idx, code in enumerate(blocks, 1):
        try:
            ast.parse(code)
        except SyntaxError as e:
            pytest.fail(f"Python block {idx} in STAGING_RUNBOOK.md failed AST parsing: {e}")

    # 2. Verify all docker compose command lines include required flags
    dc_commands = re.findall(r"(docker compose[^\n`\)]*)", content)
    assert len(dc_commands) >= 10, f"Expected at least 10 docker compose commands, found {len(dc_commands)}"
    required_flags = ["-p intranet-assistant", "--env-file .env.staging", "-f docker-compose.yml"]
    for cmd in dc_commands:
        cmd_clean = cmd.strip()
        for flag in required_flags:
            assert flag in cmd_clean, f"Docker Compose command in runbook missing '{flag}': {cmd_clean}"


def test_disposable_wal_backup_and_service_stopped_rollback():
    """Verify SQLite WAL atomic snapshot creation, pointer recording, and service-stopped rollback restoration."""
    with tempfile.TemporaryDirectory() as td:
        base_dir = Path(td)
        storage_dir = base_dir / "auth_storage"
        storage_dir.mkdir()
        backup_dir = base_dir / "backups"
        backup_dir.mkdir()

        live_db = storage_dir / "auth.sqlite3"

        # 1. Initialize store with sample user
        store = SqliteAuthStore(db_path=live_db, is_production=True, iterations=1000)
        store.create_user("rollback_user", "RollbackPass123!", "Rollback User", ["hr"])
        assert store.authenticate("rollback_user", "RollbackPass123!") is not None

        # 2. Perform online WAL checkpoint and atomic backup using Python sqlite3 API
        snapshot_path = backup_dir / "auth.sqlite3.snapshot.20261017_120000"
        src_conn = sqlite3.connect(live_db)
        src_conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        dst_conn = sqlite3.connect(snapshot_path)
        with dst_conn:
            src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()

        # Record exact snapshot path to pointer file
        pointer_file = backup_dir / "latest_verified_snapshot.txt"
        pointer_file.write_text(str(snapshot_path), encoding="utf-8")
        assert snapshot_path.exists()

        # 3. Simulate failure / corruption in live database
        bad_conn = sqlite3.connect(live_db)
        with bad_conn:
            bad_conn.execute("DROP TABLE accounts;")
        bad_conn.close()

        # Verify broken state
        broken_conn = sqlite3.connect(live_db)
        cur = broken_conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='accounts';")
        assert cur.fetchone() is None
        broken_conn.close()

        # 4. Service-stopped rollback: clean up stale WAL/SHM and copy snapshot over live DB
        target_snapshot = Path(pointer_file.read_text(encoding="utf-8").strip())
        assert target_snapshot.exists()

        wal_file = storage_dir / "auth.sqlite3-wal"
        shm_file = storage_dir / "auth.sqlite3-shm"
        if wal_file.exists():
            wal_file.unlink()
        if shm_file.exists():
            shm_file.unlink()

        import shutil
        shutil.copy2(target_snapshot, live_db)

        # 5. Verify restored database
        restored_store = SqliteAuthStore(db_path=live_db, is_production=True, iterations=1000)
        restored_user = restored_store.authenticate("rollback_user", "RollbackPass123!")
        assert restored_user is not None
        assert restored_user.username == "rollback_user"
        assert restored_user.roles == ["hr"]


def verify_image_digests(
    available_images: dict[str, str],
    expected_digests: dict[str, str],
) -> tuple[bool, list[str]]:
    """Helper implementing the preflight image comparison logic."""
    errors = []
    for image_name, expected_digest in expected_digests.items():
        if image_name not in available_images:
            errors.append(f"Image '{image_name}' is missing from local engine")
            continue
        actual_id = available_images[image_name]
        if actual_id != expected_digest:
            errors.append(f"Image '{image_name}' digest mismatch: expected '{expected_digest}', got '{actual_id}'")
    return len(errors) == 0, errors


def test_preflight_image_comparison_logic():
    """Verify that image comparison succeeds on matching digests and fails on missing or mismatched digests."""
    expected = {
        "nginx:1.27.2-alpine": "sha256:4d7083a00f2e230303e67b2d5a3b98c7e6d5c4b3a2f1e0d9c8b7a6f5e4d3c2b1",
        "intranet-assistant-app:1.0.0": "sha256:c7e3f89012a4b56789def0123456789a0bcde1234567890abcdef1234567890a",
        "internal-registry.local/vllm-openai:v0.6.3": "sha256:7f8e9d0c1b2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c",
    }

    # Case 1: Exact match
    ok, errors = verify_image_digests(dict(expected), expected)
    assert ok is True
    assert len(errors) == 0

    # Case 2: Missing image fails
    subset = dict(expected)
    del subset["nginx:1.27.2-alpine"]
    ok, errors = verify_image_digests(subset, expected)
    assert ok is False
    assert any("nginx:1.27.2-alpine" in err and "missing" in err for err in errors)

    # Case 3: Mismatched image digest fails
    tampered = dict(expected)
    tampered["intranet-assistant-app:1.0.0"] = "sha256:bad0000000000000000000000000000000000000000000000000000000000000"
    ok, errors = verify_image_digests(tampered, expected)
    assert ok is False
    assert any("intranet-assistant-app:1.0.0" in err and "digest mismatch" in err for err in errors)


def test_sqlite_auth_store_create_user_audits_failures_and_admin_separation():
    """Verify that SqliteAuthStore.create_user records audit failure events on invalid passwords, duplicate accounts, and attributes privileged creators."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "auth.sqlite3"
        store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)

        # 1. Short password fails and is audited with denied outcome
        with pytest.raises(ValueError, match="at least 8 characters"):
            store.create_user(
                username="short_pw_user",
                password="123",
                full_name="Short PW User",
                roles=["engineer"],
                actor="host_operator:audited_operator|ticket:CHG-20261017-001",
            )
        audit_events = store.list_admin_audit_events()
        short_pw_event = next(e for e in audit_events if e["target"] == "short_pw_user")
        assert short_pw_event["outcome"] == "denied"
        assert "at least 8 characters" in short_pw_event["details"]["error"]
        assert "host_operator:audited_operator" in short_pw_event["actor"]

        # 2. Legitimate user creation succeeds with allowed outcome
        user = store.create_user(
            username="valid_user",
            password="ValidPassword123!",
            full_name="Valid User",
            roles=["engineer"],
            actor="host_operator:audited_operator|ticket:CHG-20261017-001",
        )
        assert user.username == "valid_user"
        audit_events = store.list_admin_audit_events()
        allowed_event = next(e for e in audit_events if e["target"] == "valid_user" and e["outcome"] == "allowed")
        assert "host_operator:audited_operator" in allowed_event["actor"]

        # 3. Duplicate user creation fails and is audited with denied outcome
        with pytest.raises(ValueError, match="already exists"):
            store.create_user(
                username="valid_user",
                password="AnotherPassword123!",
                full_name="Valid User Duplicate",
                roles=["engineer"],
                actor="host_operator:audited_operator|ticket:CHG-20261017-001",
            )
        audit_events = store.list_admin_audit_events()
        duplicate_event = next(e for e in audit_events if e["target"] == "valid_user" and e["outcome"] == "denied")
        assert "already exists" in duplicate_event["details"]["error"]


def test_operator_identity_spoofing_via_arbitrary_sudo_user_fails_closed():
    """Verify that an arbitrary SUDO_USER environment value differing from kernel audit loginuid is rejected and fails closed."""
    from unittest.mock import patch, MagicMock

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "auth.sqlite3"
        store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)

        mock_pwd = MagicMock()
        mock_pw_entry = MagicMock()
        mock_pw_entry.pw_name = "genuine_alice"
        mock_pw_entry.pw_uid = 1005
        mock_pwd.getpwuid.return_value = mock_pw_entry

        # Spoof attempt: loginuid is genuine_alice (1005), but SUDO_USER is set to rogue_operator
        with patch.dict(os.environ, {"SUDO_USER": "rogue_operator", "SUDO_UID": "1006"}), \
             patch("pathlib.Path.exists", return_value=True), \
             patch("pathlib.Path.read_text", return_value="1005\n"), \
             patch("os.geteuid", create=True, return_value=0), \
             patch.dict("sys.modules", {"pwd": mock_pwd, "grp": MagicMock()}):

            from app.auth.accounts import resolve_trusted_operator_identity

            with pytest.raises(ValueError, match="Operator identity spoofing detected"):
                resolve_trusted_operator_identity(candidate_operator="rogue_operator", allow_posix_kernel_audit=True)

            # Privileged provisioning fails closed and logs denied audit event
            with pytest.raises(ValueError, match="spoofing detected"):
                store.provision_privileged_admin(
                    username="spoofed_admin",
                    password="AdminPassword123!",
                    ticket="SEC-2026-ADM-01",
                    approval_ref="CAB-APP-202610-092",
                    operator="rogue_operator",
                    independent_approver="cab_chair_morris",
                    manual_attestation=True,
                    operator_verifier=lambda op: resolve_trusted_operator_identity(op, allow_posix_kernel_audit=True),
                )

        assert store.get_user("spoofed_admin") is None
        events = store.list_admin_audit_events()
        spoofed_event = next(e for e in events if e["target"] == "spoofed_admin")
        assert spoofed_event["outcome"] == "denied"
        assert "spoofing detected" in spoofed_event["details"]["error"]


def test_operator_unauthorized_group_fails_closed():
    """Verify that an operator who is authenticated but not a member of authorized administrative groups fails closed."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "auth.sqlite3"
        store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)

        # Operator is in staff/contractor groups, but not sudo/wheel/secops/admin
        unauthorized_groups = {"unauthorized_alice": ["staff", "contractor"]}

        with pytest.raises(ValueError, match="not authorized"):
            store.provision_privileged_admin(
                username="unauth_admin",
                password="AdminPassword123!",
                ticket="SEC-2026-ADM-01",
                approval_ref="CAB-APP-202610-092",
                operator="unauthorized_alice",
                independent_approver="cab_chair_morris",
                manual_attestation=True,
                operator_verifier=unauthorized_groups,
            )

        assert store.get_user("unauth_admin") is None
        events = store.list_admin_audit_events()
        unauth_event = next(e for e in events if e["target"] == "unauth_admin")
        assert unauth_event["outcome"] == "denied"
        assert "not authorized" in unauth_event["details"]["error"]


def test_operator_missing_or_root_or_nobody_fails_closed():
    """Verify that missing, root, nobody, or daemon operators fail closed immediately."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "auth.sqlite3"
        store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)

        for disallowed in ["", "root", "nobody", "daemon", "unknown"]:
            target_user = f"adm_for_{disallowed or 'empty'}"
            with pytest.raises(ValueError, match="Missing or unauthorized host operator identity"):
                store.provision_privileged_admin(
                    username=target_user,
                    password="AdminPassword123!",
                    ticket="SEC-2026-ADM-01",
                    approval_ref="CAB-APP-202610-092",
                    operator=disallowed,
                    independent_approver="cab_chair_morris",
                    manual_attestation=True,
                )
            assert store.get_user(target_user) is None
            events = store.list_admin_audit_events()
            disallowed_event = next(e for e in events if e["target"] == target_user)
            assert disallowed_event["outcome"] == "denied"


def test_operator_kernel_loginuid_unset_and_invalid_fails_closed():
    """Verify that an unset kernel loginuid (4294967295), non-numeric, or negative loginuid fails closed immediately."""
    from unittest.mock import patch, MagicMock
    from app.auth.accounts import resolve_trusted_operator_identity

    mock_pwd = MagicMock()
    mock_pw_entry = MagicMock()
    mock_pw_entry.pw_name = "test_operator"
    mock_pw_entry.pw_uid = 1001
    mock_pwd.getpwuid.return_value = mock_pw_entry
    mock_pwd.getpwnam.return_value = mock_pw_entry

    # 1. Unset loginuid (4294967295)
    with patch.dict(os.environ, {"SUDO_USER": "test_operator", "SUDO_UID": "1001"}), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text", return_value="4294967295\n"), \
         patch("os.geteuid", create=True, return_value=0), \
         patch.dict("sys.modules", {"pwd": mock_pwd, "grp": MagicMock()}):

        with pytest.raises(ValueError, match="Unset or invalid kernel audit loginuid"):
            resolve_trusted_operator_identity(allow_posix_kernel_audit=True)

    # 2. Unparseable/invalid loginuid format
    with patch.dict(os.environ, {"SUDO_USER": "test_operator", "SUDO_UID": "1001"}), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text", return_value="invalid_non_numeric\n"), \
         patch("os.geteuid", create=True, return_value=0), \
         patch.dict("sys.modules", {"pwd": mock_pwd, "grp": MagicMock()}):

        with pytest.raises(ValueError, match="Invalid or unreadable kernel audit loginuid"):
            resolve_trusted_operator_identity(allow_posix_kernel_audit=True)

    # 3. Negative loginuid
    with patch.dict(os.environ, {"SUDO_USER": "test_operator", "SUDO_UID": "1001"}), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text", return_value="-1\n"), \
         patch("os.geteuid", create=True, return_value=0), \
         patch.dict("sys.modules", {"pwd": mock_pwd, "grp": MagicMock()}):

        with pytest.raises(ValueError, match="Unset or invalid kernel audit loginuid"):
            resolve_trusted_operator_identity(allow_posix_kernel_audit=True)


def test_operator_direct_root_login_fails_closed():
    """Verify that direct root login (kernel loginuid == 0 or SUDO_USER == 'root') is strictly rejected."""
    from unittest.mock import patch, MagicMock
    from app.auth.accounts import resolve_trusted_operator_identity

    mock_pwd = MagicMock()
    mock_root = MagicMock()
    mock_root.pw_name = "root"
    mock_root.pw_uid = 0
    mock_pwd.getpwuid.return_value = mock_root
    mock_pwd.getpwnam.return_value = mock_root

    # 1. Kernel audit loginuid is 0 (direct root login)
    with patch.dict(os.environ, {"SUDO_USER": "root", "SUDO_UID": "0"}), \
         patch("pathlib.Path.exists", return_value=True), \
         patch("pathlib.Path.read_text", return_value="0\n"), \
         patch("os.geteuid", create=True, return_value=0), \
         patch.dict("sys.modules", {"pwd": mock_pwd, "grp": MagicMock()}):

        with pytest.raises(ValueError, match="Direct root login is prohibited"):
            resolve_trusted_operator_identity(allow_posix_kernel_audit=True)

    # 2. SUDO_USER is root
    with patch.dict(os.environ, {"SUDO_USER": "root", "SUDO_UID": "0"}), \
         patch("pathlib.Path.exists", return_value=False), \
         patch("os.geteuid", create=True, return_value=0), \
         patch.dict("sys.modules", {"pwd": mock_pwd, "grp": MagicMock()}):

        with pytest.raises(ValueError, match="Direct root login or system daemon invocation is prohibited"):
            resolve_trusted_operator_identity(allow_posix_kernel_audit=True)


def test_operator_missing_sudo_metadata_fails_closed():
    """Verify that executing under root without sudo session metadata (SUDO_USER/SUDO_UID) fails closed."""
    from unittest.mock import patch, MagicMock
    from app.auth.accounts import resolve_trusted_operator_identity

    clean_env = {k: v for k, v in os.environ.items() if k not in ("SUDO_USER", "SUDO_UID")}

    with patch.dict(os.environ, clean_env, clear=True), \
         patch("pathlib.Path.exists", return_value=False), \
         patch("os.geteuid", create=True, return_value=0), \
         patch.dict("sys.modules", {"pwd": MagicMock(), "grp": MagicMock()}):

        with pytest.raises(ValueError, match="Missing sudo invocation metadata"):
            resolve_trusted_operator_identity(allow_posix_kernel_audit=True)


def test_two_person_rule_segregation_of_duties_enforced():
    """Verify that the air-gapped manual approval flow strictly enforces the two-person rule (segregation of duties)."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "auth.sqlite3"
        store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)

        # 1. Operator attempts to act as their own approver (self-approval)
        with pytest.raises(ValueError, match="Segregation of duties violation"):
            store.provision_privileged_admin(
                username="self_approved_adm",
                password="AdminPassword123!",
                ticket="CHG-20261017-001",
                approval_ref="CAB-APP-202610-092",
                operator="secops_operator",
                independent_approver="secops_operator",  # Self-approval!
                manual_attestation=True,
            )
        assert store.get_user("self_approved_adm") is None
        events = store.list_admin_audit_events()
        self_event = next(e for e in events if e["target"] == "self_approved_adm")
        assert self_event["outcome"] == "denied"
        assert "Segregation of duties violation" in self_event["details"]["error"]

        # 2. Missing independent approver
        with pytest.raises(ValueError, match="Independent approval required"):
            store.provision_privileged_admin(
                username="no_approver_adm",
                password="AdminPassword123!",
                ticket="CHG-20261017-001",
                approval_ref="CAB-APP-202610-092",
                operator="secops_operator",
                independent_approver="",  # Missing!
                manual_attestation=True,
            )
        assert store.get_user("no_approver_adm") is None
        events = store.list_admin_audit_events()
        no_appr_event = next(e for e in events if e["target"] == "no_approver_adm")
        assert no_appr_event["outcome"] == "denied"
        assert "Independent approval required" in no_appr_event["details"]["error"]

        # 3. Two distinct individuals (implementer operator != independent CAB approver) -> succeeds
        valid_account = store.provision_privileged_admin(
            username="two_person_adm",
            password="AdminPassword123!",
            ticket="CHG-20261017-001",
            approval_ref="CAB-APP-202610-092",
            operator="secops_operator",
            independent_approver="cab_chair_morris",
            manual_attestation=True,
        )
        assert valid_account is not None
        assert valid_account.username == "two_person_adm"
        events = store.list_admin_audit_events()
        success_event = next(e for e in events if e["target"] == "two_person_adm" and e["outcome"] == "allowed")
        assert success_event["details"]["operator"] == "secops_operator"
        assert success_event["details"]["independent_approver"] == "cab_chair_morris"


def test_itsm_network_error_and_invalid_response_fails_closed():
    """Verify that network errors, HTTP 500 errors, and malformed responses from ITSM fail closed immediately."""
    import urllib.error

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "auth.sqlite3"
        store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)

        # 1. Network / connection failure
        def mock_net_fail(t):
            raise urllib.error.URLError("Connection refused by remote host")

        with pytest.raises(ValueError, match="ITSM verification failed"):
            store.provision_privileged_admin(
                username="net_err_adm",
                password="AdminPassword123!",
                ticket="CHG-20261017-001",
                approval_ref="CAB-APP-202610-092",
                operator="secops_operator",
                itsm_client=mock_net_fail,
            )
        assert store.get_user("net_err_adm") is None
        events = store.list_admin_audit_events()
        net_event = next(e for e in events if e["target"] == "net_err_adm")
        assert net_event["outcome"] == "denied"

        # 2. HTTP 500 Internal Server Error
        def mock_500_fail(t):
            raise urllib.error.HTTPError(
                url="http://itsm.local/changes",
                code=500,
                msg="Internal Server Error",
                hdrs={},
                fp=None,
            )

        with pytest.raises(ValueError, match="ITSM verification failed"):
            store.provision_privileged_admin(
                username="http_err_adm",
                password="AdminPassword123!",
                ticket="CHG-20261017-001",
                approval_ref="CAB-APP-202610-092",
                operator="secops_operator",
                itsm_client=mock_500_fail,
            )
        assert store.get_user("http_err_adm") is None

        # 3. Malformed / empty response
        mock_empty_client = lambda t: None
        with pytest.raises(ValueError, match="ITSM verification failed"):
            store.provision_privileged_admin(
                username="empty_resp_adm",
                password="AdminPassword123!",
                ticket="CHG-20261017-001",
                approval_ref="CAB-APP-202610-092",
                operator="secops_operator",
                itsm_client=mock_empty_client,
            )
        assert store.get_user("empty_resp_adm") is None


def test_audit_storage_failure_fails_closed_without_creating_account():
    """Verify that an audit storage failure rolls back the entire transaction, preventing privileged account creation without an audit trail."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "auth.sqlite3"
        store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)

        # Install SQLite trigger: raise error on INSERT into admin_audit_events
        conn = sqlite3.connect(db_path)
        with conn:
            conn.execute(
                """
                CREATE TRIGGER fail_admin_audit_insert
                BEFORE INSERT ON admin_audit_events
                BEGIN
                    SELECT RAISE(FAIL, 'Simulated disk I/O audit storage failure');
                END;
                """
            )
        conn.close()

        with pytest.raises(sqlite3.Error, match="Simulated disk I/O audit storage failure"):
            store.provision_privileged_admin(
                username="failing_audit_adm",
                password="AdminPassword123!",
                ticket="CHG-20261017-001",
                approval_ref="CAB-APP-202610-092",
                operator="secops_operator",
                independent_approver="cab_chair_morris",
                manual_attestation=True,
            )

        # Verify that the atomic transaction rolled back and NO account exists in the database
        assert store.get_user("failing_audit_adm") is None


def test_account_identifiers_not_altered_to_encode_approval_evidence():
    """Verify that account identifiers (username and full_name) are preserved cleanly without encoding approval strings, and sensitive material is excluded from logs."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "auth.sqlite3"
        store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)

        account = store.provision_privileged_admin(
            username="clean_admin_user",
            password="CleanAdminPassword123!",
            ticket="CHG-20261017-001",
            approval_ref="CAB-APP-202610-092",
            operator="secops_operator",
            independent_approver="cab_chair_morris",
            manual_attestation=True,
        )

        # Account identifiers must NOT contain ticket, operator, or approval tokens
        assert account.username == "clean_admin_user"
        assert account.full_name == "Staging Administrator"
        assert "CHG-" not in account.username
        assert "CHG-" not in account.full_name
        assert "secops_operator" not in account.full_name
        assert "CAB-APP-" not in account.full_name

        # All approval evidence must be stored strictly as structured metadata in admin_audit_events
        events = store.list_admin_audit_events()
        admin_event = next(e for e in events if e["target"] == "clean_admin_user" and e["outcome"] == "allowed")

        details = admin_event["details"]
        assert details["ticket"] == "CHG-20261017-001"
        assert details["approval_ref"] == "CAB-APP-202610-092"
        assert details["operator"] == "secops_operator"
        assert details["independent_approver"] == "cab_chair_morris"
        assert details["verification_method"] == "air_gapped_two_person_verification"
        assert details["status"] == "APPROVED"

        # Verify zero sensitive material (passwords, hashes, salts, session tokens) in details or actor
        details_str = json.dumps(details)
        assert "CleanAdminPassword123!" not in details_str
        assert "password" not in details
        assert "password_hash" not in details
        assert "salt" not in details
        assert "token" not in details


def test_unauthorized_approver_fails_closed():
    """Verify that an approver not recognized as an authorized CAB Chair or SecOps Lead fails closed immediately."""
    from app.auth.accounts import verify_change_approval

    # 1. Direct verify_change_approval raises PermissionError
    with pytest.raises(PermissionError, match="is not authorized to approve privileged changes"):
        verify_change_approval(
            ticket="CHG-20261017-001",
            approval_ref="CAB-APP-202610-092",
            operator="secops_operator",
            independent_approver="unauthorized_mallory",
            manual_attestation=True,
        )

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "auth.sqlite3"
        store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)

        # 2. User-supplied arbitrary approver not in AUTHORIZED_CHANGE_APPROVERS via store fails closed
        with pytest.raises(ValueError, match="is not authorized to approve privileged changes") as exc_info:
            store.provision_privileged_admin(
                username="unauthorized_appr_adm",
                password="AdminPassword123!",
                ticket="CHG-20261017-001",
                approval_ref="CAB-APP-202610-092",
                operator="secops_operator",
                independent_approver="unauthorized_mallory",
                manual_attestation=True,
            )
        assert isinstance(exc_info.value.__cause__, PermissionError)
        assert store.get_user("unauthorized_appr_adm") is None
        events = store.list_admin_audit_events()
        event = next(e for e in events if e["target"] == "unauthorized_appr_adm")
        assert event["outcome"] == "denied"
        assert "not authorized to approve privileged changes" in event["details"]["error"]

        # 3. Custom authorized approver set restriction
        with pytest.raises(ValueError, match="is not authorized to approve privileged changes") as exc_info2:
            store.provision_privileged_admin(
                username="restricted_appr_adm",
                password="AdminPassword123!",
                ticket="CHG-20261017-001",
                approval_ref="CAB-APP-202610-092",
                operator="secops_operator",
                independent_approver="cab_chair_morris",
                authorized_approvers=frozenset({"secops_lead_carol"}),  # Morris excluded
                manual_attestation=True,
            )
        assert isinstance(exc_info2.value.__cause__, PermissionError)
        assert store.get_user("restricted_appr_adm") is None


def test_missing_and_unverifiable_approver_evidence_fails_closed():
    """Verify that missing tickets, missing approval references, invalid reference formats, or absent attestation fail closed."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "auth.sqlite3"
        store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)

        # 1. Missing ticket
        with pytest.raises(ValueError, match="Missing change ticket"):
            store.provision_privileged_admin(
                username="missing_tk_adm",
                password="AdminPassword123!",
                ticket="",
                approval_ref="CAB-APP-202610-092",
                operator="secops_operator",
                independent_approver="cab_chair_morris",
                manual_attestation=True,
            )
        assert store.get_user("missing_tk_adm") is None

        # 2. Missing approval reference
        with pytest.raises(ValueError, match="Missing approval evidence"):
            store.provision_privileged_admin(
                username="missing_ref_adm",
                password="AdminPassword123!",
                ticket="CHG-20261017-001",
                approval_ref="",
                operator="secops_operator",
                independent_approver="cab_chair_morris",
                manual_attestation=True,
            )
        assert store.get_user("missing_ref_adm") is None

        # 3. Arbitrary / invalid approval reference format
        with pytest.raises(ValueError, match="Inadequate approval evidence"):
            store.provision_privileged_admin(
                username="arbitrary_ref_adm",
                password="AdminPassword123!",
                ticket="CHG-20261017-001",
                approval_ref="arbitrary_approval_token_12345",
                operator="secops_operator",
                independent_approver="cab_chair_morris",
                manual_attestation=True,
            )
        assert store.get_user("arbitrary_ref_adm") is None

        # 4. Absent manual attestation in air-gapped flow
        with pytest.raises(ValueError, match="Manual approval verification required"):
            store.provision_privileged_admin(
                username="no_attest_adm",
                password="AdminPassword123!",
                ticket="CHG-20261017-001",
                approval_ref="CAB-APP-202610-092",
                operator="secops_operator",
                independent_approver="cab_chair_morris",
                manual_attestation=False,
            )
        assert store.get_user("no_attest_adm") is None


def test_itsm_self_approval_and_mismatched_approver_fails_closed():
    """Verify that ITSM records indicating operator self-approval, approver mismatch, or unauthorized approver fail closed."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "auth.sqlite3"
        store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)

        # 1. ITSM record shows the operator approved their own ticket (self-approval in ITSM)
        mock_self_approval_client = lambda t: {
            "status": "APPROVED",
            "target_system": "intranet-assistant",
            "approval_id": "CAB-APP-202610-092",
            "approver": "secops_operator",  # Same as operator!
        }
        with pytest.raises(ValueError, match="Segregation of duties violation: ITSM record shows change ticket"):
            store.provision_privileged_admin(
                username="itsm_self_adm",
                password="AdminPassword123!",
                ticket="CHG-20261017-001",
                approval_ref="CAB-APP-202610-092",
                operator="secops_operator",
                itsm_client=mock_self_approval_client,
            )
        assert store.get_user("itsm_self_adm") is None

        # 2. Supplied independent approver does not match the official ITSM approver
        mock_mismatch_client = lambda t: {
            "status": "APPROVED",
            "target_system": "intranet-assistant",
            "approval_id": "CAB-APP-202610-092",
            "approver": "cab_chair_morris",
        }
        with pytest.raises(ValueError, match="ITSM verification failed: Supplied approver"):
            store.provision_privileged_admin(
                username="itsm_mismatch_adm",
                password="AdminPassword123!",
                ticket="CHG-20261017-001",
                approval_ref="CAB-APP-202610-092",
                operator="secops_operator",
                independent_approver="secops_lead_carol",  # Mismatch with Morris!
                itsm_client=mock_mismatch_client,
            )
        assert store.get_user("itsm_mismatch_adm") is None

        # 3. ITSM record lists an unauthorized approver
        mock_unauthorized_approver_client = lambda t: {
            "status": "APPROVED",
            "target_system": "intranet-assistant",
            "approval_id": "CAB-APP-202610-092",
            "approver": "unauthorized_external_guest",
        }
        with pytest.raises(ValueError, match="is not an authorized change approver") as exc_info3:
            store.provision_privileged_admin(
                username="itsm_unauth_adm",
                password="AdminPassword123!",
                ticket="CHG-20261017-001",
                approval_ref="CAB-APP-202610-092",
                operator="secops_operator",
                itsm_client=mock_unauthorized_approver_client,
            )
        assert isinstance(exc_info3.value.__cause__, PermissionError)
        assert store.get_user("itsm_unauth_adm") is None


def test_structured_audit_metadata_links_all_five_required_fields():
    """Verify that both air-gapped and ITSM successful provisioning link ticket, target_system, approval_ref, operator, and independent_approver."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "auth.sqlite3"
        store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)

        # 1. Air-gapped manual verification path
        air_gapped_user = store.provision_privileged_admin(
            username="air_gapped_adm",
            password="AdminPassword123!",
            ticket="CHG-20261017-001",
            approval_ref="CAB-APP-202610-092",
            operator="secops_operator",
            independent_approver="cab_chair_morris",
            manual_attestation=True,
        )
        assert air_gapped_user is not None

        events = store.list_admin_audit_events()
        air_event = next(e for e in events if e["target"] == "air_gapped_adm" and e["outcome"] == "allowed")
        details = air_event["details"]

        # Assert all 5 fields explicitly linked in structured metadata
        assert details["ticket"] == "CHG-20261017-001"
        assert details["target_system"] == "intranet-assistant"
        assert details["approval_ref"] == "CAB-APP-202610-092"
        assert details["operator"] == "secops_operator"
        assert details["independent_approver"] == "cab_chair_morris"
        assert details["verification_method"] == "air_gapped_two_person_verification"
        assert details["status"] == "APPROVED"

        # 2. Automated ITSM verification path
        mock_itsm_client = lambda t: {
            "status": "APPROVED",
            "target_system": "intranet-assistant",
            "approval_id": "CAB-APP-202610-093",
            "approver": "secops_lead_carol",
        }
        itsm_user = store.provision_privileged_admin(
            username="itsm_verified_adm",
            password="AdminPassword123!",
            ticket="SEC-2026-ADM-02",
            approval_ref="CAB-APP-202610-093",
            operator="secops_operator",
            itsm_client=mock_itsm_client,
        )
        assert itsm_user is not None

        events = store.list_admin_audit_events()
        itsm_event = next(e for e in events if e["target"] == "itsm_verified_adm" and e["outcome"] == "allowed")
        details2 = itsm_event["details"]

        assert details2["ticket"] == "SEC-2026-ADM-02"
        assert details2["target_system"] == "intranet-assistant"
        assert details2["approval_ref"] == "CAB-APP-202610-093"
        assert details2["operator"] == "secops_operator"
        assert details2["independent_approver"] == "secops_lead_carol"
        assert details2["verification_method"] == "itsm_api"
        assert details2["status"] == "APPROVED"


def test_unauthorized_and_spoofed_approver_identities_fail_closed():
    """Verify that unauthorized, lookalike, or injection-attempted approver names fail closed immediately."""
    from app.auth.accounts import verify_change_approval

    spoofed_candidates = [
        "cab_chair_morris_spoofed",
        "secops_lead_carol_fake",
        "intruder",
        "cab_chair_morris; rm -rf /",
        "<script>alert(1)</script>",
        "unknown_officer",
    ]

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "auth.sqlite3"
        store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)

        for candidate in spoofed_candidates:
            # 1. Direct verify_change_approval
            with pytest.raises(PermissionError, match="is not authorized to approve privileged changes"):
                verify_change_approval(
                    ticket="CHG-20261017-001",
                    approval_ref="CAB-APP-202610-092",
                    operator="secops_operator",
                    independent_approver=candidate,
                    manual_attestation=True,
                )

            # 2. Provisioning attempt via store fails closed and audits denied
            target_user = f"spoof_adm_{abs(hash(candidate)) % 10000}"
            with pytest.raises(ValueError, match="is not authorized to approve privileged changes"):
                store.provision_privileged_admin(
                    username=target_user,
                    password="AdminPassword123!",
                    ticket="CHG-20261017-001",
                    approval_ref="CAB-APP-202610-092",
                    operator="secops_operator",
                    independent_approver=candidate,
                    manual_attestation=True,
                )
            assert store.get_user(target_user) is None
            events = store.list_admin_audit_events()
            denied_event = next(e for e in events if e["target"] == target_user and e["outcome"] == "denied")
            assert "not authorized to approve privileged changes" in denied_event["details"]["error"]


def test_attempts_to_modify_or_bypass_approver_authorization_fail_closed():
    """Verify that callers cannot inject unauthorized approvers via parameters, config files, or env vars."""
    from unittest.mock import patch
    from app.auth.accounts import get_authorized_change_approvers, verify_change_approval

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "auth.sqlite3"
        store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)

        # 1. Caller attempts to supply custom authorized_approvers containing unauthorized names
        with pytest.raises(ValueError, match="Approver authorization bypass attempt detected") as exc_info:
            store.provision_privileged_admin(
                username="bypass_adm",
                password="AdminPassword123!",
                ticket="CHG-20261017-001",
                approval_ref="CAB-APP-202610-092",
                operator="secops_operator",
                independent_approver="unauthorized_mallory",
                authorized_approvers=frozenset({"unauthorized_mallory"}),  # Attempt to inject mallory
                manual_attestation=True,
            )
        assert isinstance(exc_info.value.__cause__, PermissionError)
        assert store.get_user("bypass_adm") is None

        # 2. Environment variable set to empty string fails closed
        with patch.dict(os.environ, {"AUTHORIZED_CHANGE_APPROVERS": ""}):
            with pytest.raises(ValueError, match="AUTHORIZED_CHANGE_APPROVERS is set but empty"):
                get_authorized_change_approvers()

        # 3. Environment variable containing wildcard '*' fails closed
        with patch.dict(os.environ, {"AUTHORIZED_CHANGE_APPROVERS": "*,cab_chair_morris"}):
            with pytest.raises(ValueError, match="Invalid approver name or wildcard detected"):
                get_authorized_change_approvers()

        # 4. Config file containing invalid approver tokens fails closed
        bad_cfg = Path(td) / "bad_approvers.json"
        bad_cfg.write_text(json.dumps(["cab_chair_morris", "*"]), encoding="utf-8")
        with pytest.raises(ValueError, match="Failed to load trusted approver configuration"):
            get_authorized_change_approvers(config_path=bad_cfg)


def test_itsm_service_auth_and_transport_security_enforced():
    """Verify that ITSM integration requires service tokens, HTTPS transport for remote hosts, and rejects wildcard target systems."""
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "auth.sqlite3"
        store = SqliteAuthStore(db_path=db_path, is_production=True, iterations=1000)

        # 1. Incomplete configuration: URL without Token
        with pytest.raises(ValueError, match="Incomplete ITSM integration configuration"):
            store.provision_privileged_admin(
                username="itsm_no_token_adm",
                password="AdminPassword123!",
                ticket="CHG-20261017-001",
                approval_ref="CAB-APP-202610-092",
                operator="secops_operator",
                itsm_url="https://itsm.internal.corp",
                itsm_token="",  # Missing token!
            )

        # 2. Insecure plaintext HTTP transport to remote ITSM host
        with pytest.raises(ValueError, match="Insecure ITSM transport: ITSM_API_URL must use HTTPS"):
            store.provision_privileged_admin(
                username="itsm_insecure_adm",
                password="AdminPassword123!",
                ticket="CHG-20261017-001",
                approval_ref="CAB-APP-202610-092",
                operator="secops_operator",
                itsm_url="http://itsm.remote-corp.internal",  # Insecure HTTP remote
                itsm_token="secret_token",
            )

        # 3. ITSM record with missing approver and no supplied approver fails closed
        mock_no_approver_client = lambda t: {
            "status": "APPROVED",
            "target_system": "intranet-assistant",
            "approval_id": "CAB-APP-202610-092",
            # No approver or approved_by key
        }
        with pytest.raises(ValueError, match="record has no recorded approver"):
            store.provision_privileged_admin(
                username="itsm_no_appr_adm",
                password="AdminPassword123!",
                ticket="CHG-20261017-001",
                approval_ref="CAB-APP-202610-092",
                operator="secops_operator",
                itsm_client=mock_no_approver_client,
            )

        # 4. ITSM record targeting wildcard '*' rejected for privileged provisioning
        mock_wildcard_target = lambda t: {
            "status": "APPROVED",
            "target_system": "*",  # Broad wildcard
            "approval_id": "CAB-APP-202610-092",
            "approver": "cab_chair_morris",
        }
        with pytest.raises(ValueError, match="does not match 'intranet-assistant'"):
            store.provision_privileged_admin(
                username="itsm_wildcard_adm",
                password="AdminPassword123!",
                ticket="CHG-20261017-001",
                approval_ref="CAB-APP-202610-092",
                operator="secops_operator",
                itsm_client=mock_wildcard_target,
            )


def test_jsonl_audit_sink_disk_failure_fails_closed(tmp_path: Path):
    """Verify that JsonlAuditSink raises OSError on disk write failure and does not silently swallow errors."""
    from unittest.mock import patch
    from app.audit import JsonlAuditSink, new_event

    log_file = tmp_path / "failing_audit.jsonl"
    sink = JsonlAuditSink(log_file)
    event = new_event("privileged_admin_provision", "allowed", "req-test-fail", "secops_operator", "admin")

    # Simulate disk failure by patching Path.open to raise OSError
    with patch.object(Path, "open", side_effect=OSError("Disk quota exceeded (simulated I/O failure)")):
        with pytest.raises(OSError, match="Disk quota exceeded"):
            sink.record(event)


def test_approver_configuration_integrity_and_fail_closed_invariants(tmp_path: Path):
    """Verify that approver configuration loading enforces explicit production files,
    prohibits silent fallbacks to dev constants or untrusted env vars in production,
    enforces POSIX permission/symlink boundaries, and fails closed on empty or missing files."""
    from unittest.mock import MagicMock, patch
    from app.auth.accounts import (
        DEFAULT_PRODUCTION_APPROVERS_CONFIG,
        get_authorized_change_approvers,
    )

    # 1. Non-existent explicit config_path raises FileNotFoundError (no silent fallback)
    missing_cfg = tmp_path / "does_not_exist.json"
    with pytest.raises(FileNotFoundError, match="Trusted approver configuration file not found"):
        get_authorized_change_approvers(config_path=missing_cfg, is_production=False)

    # 2. Production mode with missing default configuration fails closed without falling back to constants
    with patch.dict(os.environ, {"APP_ENV": "production", "APPROVERS_CONFIG_FILE": ""}, clear=False):
        with pytest.raises(FileNotFoundError, match="Trusted approver configuration file not found"):
            get_authorized_change_approvers(is_production=True)

    # 3. Production mode rejects untrusted AUTHORIZED_CHANGE_APPROVERS environment variable bypass
    with patch.dict(os.environ, {"APP_ENV": "production", "AUTHORIZED_CHANGE_APPROVERS": "untrusted_mallory"}):
        with pytest.raises(FileNotFoundError, match="Trusted approver configuration file not found"):
            get_authorized_change_approvers(is_production=True)

    # 4. Empty configuration file fails closed
    empty_cfg = tmp_path / "empty_approvers.json"
    empty_cfg.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="contains no valid approvers"):
        get_authorized_change_approvers(config_path=empty_cfg, is_production=False)

    # 5. POSIX permissions checks (unit test with mocked stat for cross-platform validation)
    valid_cfg = tmp_path / "valid_approvers.json"
    valid_cfg.write_text(json.dumps(["cab_chair_morris"]), encoding="utf-8")

    # 5a. World-writable file fails closed with PermissionError
    mock_world_writable_stat = MagicMock(st_mode=0o100666, st_uid=0)
    with patch("os.name", "posix"):
        with patch.object(Path, "stat", return_value=mock_world_writable_stat):
            with pytest.raises(PermissionError, match="file is world-writable"):
                get_authorized_change_approvers(config_path=valid_cfg, is_production=False)

    # 5b. Group-writable file fails closed with PermissionError
    mock_group_writable_stat = MagicMock(st_mode=0o100660, st_uid=0)
    with patch("os.name", "posix"):
        with patch.object(Path, "stat", return_value=mock_group_writable_stat):
            with pytest.raises(PermissionError, match="file is group-writable"):
                get_authorized_change_approvers(config_path=valid_cfg, is_production=False)

    # 5c. Non-root ownership when executing as root fails closed
    mock_non_root_stat = MagicMock(st_mode=0o100644, st_uid=1000)
    with patch("os.name", "posix"):
        with patch("os.geteuid", return_value=0, create=True):
            with patch.object(Path, "stat", return_value=mock_non_root_stat):
                with pytest.raises(PermissionError, match="file is owned by UID 1000, expected root"):
                    get_authorized_change_approvers(config_path=valid_cfg, is_production=False)

    # 5d. Symlink owned by non-root when executing as root fails closed
    mock_safe_stat = MagicMock(st_mode=0o100644, st_uid=0)
    mock_untrusted_symlink_stat = MagicMock(st_uid=1001)
    with patch("os.name", "posix"):
        with patch("os.geteuid", return_value=0, create=True):
            with patch.object(Path, "is_symlink", return_value=True):
                with patch.object(Path, "lstat", return_value=mock_untrusted_symlink_stat):
                    with patch.object(Path, "stat", return_value=mock_safe_stat):
                        with pytest.raises(PermissionError, match="symlink is owned by UID 1001, expected root"):
                            get_authorized_change_approvers(config_path=valid_cfg, is_production=False)

    # 6. Valid configuration file successfully loads
    approvers = get_authorized_change_approvers(config_path=valid_cfg, is_production=False)
    assert approvers == frozenset({"cab_chair_morris"})




