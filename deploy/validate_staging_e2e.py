"""End-to-end automated verification of the containerized staging stack.

Tests the full HTTPS production deployment through Nginx on port 443:
1. TLS & HTTP->HTTPS Redirection
2. Health & Readiness endpoints
3. Hardened Production Auth (config lockdown, rejection of demo accounts, secure cookies)
4. Authenticated RBAC & Document Access Controls (MCP tool invocation, admin permission fences)
5. Chat orchestration through internal LLM service
6. Edge rate-limiting and overload admission controls
7. Session Invalidation on Logout
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import sys
import time
import urllib3
import requests

# Disable insecure cert warnings for internal self-signed staging cert
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HTTPS_BASE = "https://127.0.0.1"
HTTP_BASE = "http://127.0.0.1"
ORIGIN = "https://intranet-staging.company.internal"
CERT_PATH = "deploy/certs/server.crt"
HEADERS_BASE = {
    "Host": "intranet-staging.company.internal",
    "Origin": ORIGIN,
}


def log_test(name: str):
    print(f"\n{'='*70}\n[TEST] {name}\n{'='*70}")


def run_e2e_tests():
    total_passed = 0
    total_failed = 0

    def check(desc: str, condition: bool):
        nonlocal total_passed, total_failed
        if condition:
            print(f"  [PASS] {desc}")
            total_passed += 1
        else:
            print(f"  [FAIL] {desc}")
            total_failed += 1
            raise AssertionError(f"Check failed: {desc}")

    session = requests.Session()
    session.verify = CERT_PATH

    # ---------------------------------------------------------
    # 1. TLS & HTTP -> HTTPS Redirection
    # ---------------------------------------------------------
    log_test("1. Edge TLS & HTTP -> HTTPS Redirection")
    r_redirect = requests.get(f"{HTTP_BASE}/api/v1/auth/config", headers=HEADERS_BASE, allow_redirects=False)
    check("HTTP port 80 redirects to HTTPS", r_redirect.status_code == 301)
    check("Redirect location contains https://", r_redirect.headers.get("Location", "").startswith("https://"))

    r_live = session.get(f"{HTTPS_BASE}/health/live", headers=HEADERS_BASE, timeout=5)
    check("HTTPS /health/live returns HTTP 200", r_live.status_code == 200 and r_live.json().get("status") == "alive")

    r_ready = session.get(f"{HTTPS_BASE}/health/ready", headers=HEADERS_BASE, timeout=5)
    check("HTTPS /health/ready returns HTTP 200", r_ready.status_code == 200 and r_ready.json().get("status") == "ready")

    # ---------------------------------------------------------
    # 2. Hardened Production Auth & Cookie Verification
    # ---------------------------------------------------------
    log_test("2. Hardened Production Authentication")
    r_cfg = session.get(f"{HTTPS_BASE}/api/v1/auth/config", headers=HEADERS_BASE, timeout=5)
    check("Auth config returns HTTP 200", r_cfg.status_code == 200)
    cfg = r_cfg.json()
    check("app_env is 'production'", cfg.get("app_env") == "production")
    check("Quick Sign-in is disabled in production", cfg.get("enable_quick_signin") is False)
    check("Demo accounts list is completely empty", cfg.get("demo_accounts") == [])

    # Rejection of demo account credentials
    r_demo = session.post(
        f"{HTTPS_BASE}/api/v1/auth/login",
        headers=HEADERS_BASE,
        json={"username": "alice.chen", "password": "EngineeringLead2026!"},
        timeout=5,
    )
    check("Demo account credentials rejected with HTTP 401", r_demo.status_code == 401)

    # Genuine login: Staff Engineer
    test_password = os.environ.get("STAGING_TEST_PW", "StagingSecured2026!Run")
    r_eng_login = session.post(
        f"{HTTPS_BASE}/api/v1/auth/login",
        headers=HEADERS_BASE,
        json={"username": "staff.engineer", "password": test_password},
        timeout=10,
    )
    check("Genuine staff.engineer login returns HTTP 200", r_eng_login.status_code == 200)
    eng_cookies = r_eng_login.headers.get("Set-Cookie", "")
    check("Session cookie marked HttpOnly", "HttpOnly" in eng_cookies or "httponly" in eng_cookies.lower())
    check("Session cookie marked Secure", "Secure" in eng_cookies or "secure" in eng_cookies.lower())
    check("Session cookie marked SameSite=Lax", "SameSite=Lax" in eng_cookies or "samesite=lax" in eng_cookies.lower())

    csrf_token = r_eng_login.json().get("csrf_token")
    check("Anti-CSRF token issued upon login", bool(csrf_token))

    # Verification of /api/v1/auth/me
    auth_headers = dict(HEADERS_BASE)
    auth_headers["X-CSRF-Token"] = csrf_token

    r_me = session.get(f"{HTTPS_BASE}/api/v1/auth/me", headers=auth_headers, timeout=5)
    check("Identity /auth/me returns HTTP 200", r_me.status_code == 200)
    user_info = r_me.json()
    check("Authenticated user subject is staff.engineer", user_info.get("subject") == "staff.engineer")
    check("Roles include 'engineer'", "engineer" in user_info.get("roles", []))
    check("Permissions include documents:search and engineering:read", "documents:search" in user_info.get("permissions", []) and "engineering:read" in user_info.get("permissions", []))

    # ---------------------------------------------------------
    # 3. RBAC & Document Access Controls
    # ---------------------------------------------------------
    log_test("3. RBAC & Document Access Controls")
    # 3a. Verify engineer cannot access admin endpoints (RBAC fence)
    r_admin_forbidden = session.get(
        f"{HTTPS_BASE}/api/v1/admin/users",
        headers=auth_headers,
        timeout=5,
    )
    check("Engineer denied access to admin endpoint (HTTP 403 Forbidden)", r_admin_forbidden.status_code == 403)

    # 3b. Verify engineer can invoke search_documents MCP tool
    r_doc_search = session.post(
        f"{HTTPS_BASE}/api/v1/mcp/tools/search_documents",
        headers=auth_headers,
        json={"parameters": {"query": "security architecture", "limit": 3}},
        timeout=10,
    )
    check("Engineer search_documents MCP tool returns HTTP 200", r_doc_search.status_code == 200)
    doc_payload = r_doc_search.json()
    check("Tool name is search_documents", doc_payload.get("tool") == "search_documents")
    print(f"  [INFO] Document search result content length: {len(doc_payload.get('content', ''))} characters")

    # 3c. Verify Admin privileges for Corporate Administrator
    admin_session = requests.Session()
    admin_session.verify = CERT_PATH
    r_admin_login = admin_session.post(
        f"{HTTPS_BASE}/api/v1/auth/login",
        headers=HEADERS_BASE,
        json={"username": "corp.admin", "password": test_password},
        timeout=10,
    )
    check("Admin corp.admin login returns HTTP 200", r_admin_login.status_code == 200)
    admin_csrf = r_admin_login.json().get("csrf_token")
    admin_headers = dict(HEADERS_BASE)
    admin_headers["X-CSRF-Token"] = admin_csrf

    r_admin_users = admin_session.get(f"{HTTPS_BASE}/api/v1/admin/users", headers=admin_headers, timeout=5)
    check("Admin user list returns HTTP 200", r_admin_users.status_code == 200)
    user_list = r_admin_users.json().get("users", [])
    check("Admin user list contains staged users", len(user_list) >= 3)
    print(f"  [INFO] Staged user list verified ({len(user_list)} accounts registered).")

    # ---------------------------------------------------------
    # 4. End-to-End Chat & Internal Model Inference
    # ---------------------------------------------------------
    log_test("4. End-to-End Chat via Internal LLM Service")
    chat_payload = {
        "message": "What is the corporate remote work policy and security protocol?"
    }
    r_chat = session.post(
        f"{HTTPS_BASE}/api/v1/chat",
        headers=auth_headers,
        json=chat_payload,
        timeout=30,
    )
    check("Chat request through HTTPS proxy returned HTTP 200", r_chat.status_code == 200)
    chat_resp = r_chat.json()
    reply = chat_resp.get("response", "")
    check("Chat reply is non-empty", bool(reply and len(reply) > 10))
    print(f"  [INFO] Model response snippet: {reply[:120]}...")

    # ---------------------------------------------------------
    # 5. Overload & Admission Controls Under Load
    # ---------------------------------------------------------
    log_test("5. Overload & Edge Rate Limiting Controls")
    # Test Edge Rate Limiting on Login (auth_login_zone = 5r/s burst=10)
    print("  [INFO] Firing rapid authentication burst to verify edge rate limiter...")
    rate_limited = False
    for _ in range(25):
        r_flood = requests.post(
            f"{HTTPS_BASE}/api/v1/auth/login",
            headers=HEADERS_BASE,
            json={"username": "probe.test", "password": "ProbePassword123!"},
            verify=CERT_PATH,
            timeout=2,
        )
        if r_flood.status_code == 429:
            rate_limited = True
            break

    check("Nginx edge rate limiter triggers HTTP 429 on rapid login flood", rate_limited)

    # Test Concurrent Chat In-Flight Capacity
    print("  [INFO] Testing concurrent chat requests within bounded worker slots...")
    def fire_chat():
        s = requests.Session()
        s.verify = CERT_PATH
        return s.post(
            f"{HTTPS_BASE}/api/v1/chat",
            headers=auth_headers,
            cookies=session.cookies.get_dict(),
            json={"message": "Brief summary of intranet system status"},
            timeout=20,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(fire_chat) for _ in range(4)]
        results = [f.result() for f in futures]

    statuses = [r.status_code for r in results]
    print(f"  [INFO] Concurrent chat responses: {statuses}")
    check("Concurrent requests handled safely (200 OK or 429 capacity shedding)", all(s in {200, 429, 503} for s in statuses))

    # ---------------------------------------------------------
    # 6. Session Invalidation on Logout
    # ---------------------------------------------------------
    log_test("6. Session Invalidation on Logout")
    r_logout = session.post(
        f"{HTTPS_BASE}/api/v1/auth/logout",
        headers=auth_headers,
        timeout=5,
    )
    check("Logout with valid CSRF token returns HTTP 200", r_logout.status_code == 200)

    # Verify session is revoked
    r_revoked = session.get(f"{HTTPS_BASE}/api/v1/auth/me", headers=auth_headers, timeout=5)
    check("Revoked session token rejected with HTTP 401", r_revoked.status_code == 401)

    print(f"\n{'='*70}\n[ALL TESTS PASSED] Total checks passed: {total_passed} | Failed: {total_failed}\n{'='*70}")


if __name__ == "__main__":
    try:
        run_e2e_tests()
    except Exception as e:
        print(f"\n[FATAL ERROR] {e}", file=sys.stderr)
        sys.exit(1)
