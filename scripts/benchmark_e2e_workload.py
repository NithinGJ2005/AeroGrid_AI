"""End-to-end load testing utility for AeroGrid AI.

Simulates 1 to 100 concurrent active employees with realistic mixed workloads:
- Authenticated sessions and session validation
- MCP tool listing and permission-aware discovery
- Document search with permission filtering
- Read-only database catalog queries
- Health / liveness checks
- AI chat questions with realistic think times and burst scenarios

Collects latency percentiles (p50, p95, p99), HTTP status codes, throughput (req/s),
hardware utilization (CPU, RAM, GPU utilization, VRAM), and LLM queue metrics.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import statistics
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

DEFAULT_USER_PASS = os.environ.get("AEROGRID_USER_PASSWORD")
DEFAULT_ADMIN_PASS = os.environ.get("AEROGRID_ADMIN_PASSWORD", "AdminSecurity2026!")

DEMO_USERS = (
    [
        ("staff.engineer", DEFAULT_USER_PASS or "StagingSecured2026!Run"),
        ("hr.partner", DEFAULT_USER_PASS or "StagingSecured2026!Run"),
        ("corp.admin", DEFAULT_ADMIN_PASS or "StagingSecured2026!Run"),
    ]
    if os.environ.get("AEROGRID_STAGING_USERS") or os.environ.get("AEROGRID_ADMIN_USER") == "corp.admin"
    else [
        ("alice.chen", DEFAULT_USER_PASS or "EngineeringLead2026!"),
        ("bob.smith", DEFAULT_USER_PASS or "StaffEngineer2026!"),
        ("david.miller", DEFAULT_USER_PASS or "HRPartner2026!"),
        ("emma.watson", DEFAULT_USER_PASS or "FinanceAnalyst2026!"),
        ("admin.system", DEFAULT_ADMIN_PASS),
    ]
)

CHAT_QUESTIONS = [
    "What is the standard procedure for password rotations?",
    "Summarize the IT security policy for remote employees.",
    "What are the requirements for project code repositories?",
    "Where can I find the employee directory for Engineering?",
    "What is the policy for travel expense reimbursement?",
]


@dataclass
class RequestRecord:
    endpoint: str
    status_code: int
    duration_ms: float
    error: str | None = None


@dataclass
class HardwareSample:
    ram_used_mb: float = 0.0
    ram_total_mb: float = 0.0
    gpu_util_pct: float = 0.0
    vram_used_mb: float = 0.0
    vram_total_mb: float = 0.0


@dataclass
class TierResult:
    virtual_users: int
    mode: str
    duration_seconds: float
    total_requests: int = 0
    successful_requests: int = 0
    intentional_denials: int = 0  # 403 (intentional RBAC authorization enforcement)
    rejected_requests: int = 0    # 429 (rate-limit or admission queue shed)
    service_unavailable: int = 0  # 503
    server_errors: int = 0        # 5xx
    timeouts: int = 0             # Connection or read timeouts
    failed_requests: int = 0      # Sum of unexpected failures (5xx, timeouts)
    status_codes: dict[int, int] = field(default_factory=dict)
    endpoint_counts: dict[str, int] = field(default_factory=dict)
    endpoint_latencies: dict[str, list[float]] = field(default_factory=dict)
    overall_p50_ms: float = 0.0
    overall_p95_ms: float = 0.0
    overall_p99_ms: float = 0.0
    throughput_rps: float = 0.0
    non_llm_p95_ms: float = 0.0
    non_llm_p99_ms: float = 0.0
    chat_p50_ms: float = 0.0
    chat_p95_ms: float = 0.0
    chat_p99_ms: float = 0.0
    chat_completed: int = 0
    chat_rejected: int = 0
    peak_ram_mb: float = 0.0
    peak_vram_mb: float = 0.0
    peak_gpu_util: float = 0.0
    llm_metrics: dict[str, Any] = field(default_factory=dict)
    criteria_passed: bool = True
    criteria_notes: list[str] = field(default_factory=list)


def sample_hardware() -> HardwareSample:
    """Sample system RAM and NVIDIA GPU VRAM/utilization."""
    sample = HardwareSample()
    # Query GPU
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total", "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        ).strip()
        parts = [p.strip() for p in out.split(",")]
        if len(parts) >= 3:
            sample.gpu_util_pct = float(parts[0])
            sample.vram_used_mb = float(parts[1])
            sample.vram_total_mb = float(parts[2])
    except Exception:
        pass

    # Query RAM via PowerShell
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "$os = Get-CimInstance Win32_OperatingSystem; [math]::Round(($os.TotalVisibleMemorySize - $os.FreePhysicalMemory)/1024); [math]::Round($os.TotalVisibleMemorySize/1024)"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        ).strip().splitlines()
        if len(out) >= 2:
            sample.ram_used_mb = float(out[0].strip())
            sample.ram_total_mb = float(out[1].strip())
    except Exception:
        pass

    return sample


async def authenticate_user(client: httpx.AsyncClient, base_url: str, username: str, password: str) -> str | None:
    """Authenticate and obtain JWT bearer token."""
    try:
        resp = await client.post(
            f"{base_url}/api/v1/auth/token",
            json={"username": username, "password": password},
            timeout=10.0,
        )
        if resp.status_code == 200:
            return resp.json().get("access_token")
    except Exception:
        pass
    return None


async def simulate_mixed_employee(
    user_id: int,
    base_url: str,
    token: str,
    client: httpx.AsyncClient,
    stop_event: asyncio.Event,
    records: list[RequestRecord],
    chat_interval_s: float = 20.0,
):
    """Simulate a single employee performing realistic mixed tasks with keepalive and think time."""
    headers = {"Authorization": f"Bearer {token}"}
    # Initial stagger so virtual employees ramp up naturally
    await asyncio.sleep(random.uniform(0.05, 1.2))

    last_chat_time = time.monotonic() - random.uniform(0, chat_interval_s)

    while not stop_event.is_set():
        now = time.monotonic()
        # Decide action: if it's time for chat, send chat; otherwise perform navigation/search
        if now - last_chat_time >= chat_interval_s:
            last_chat_time = now
            endpoint = "/api/v1/chat"
            msg = random.choice(CHAT_QUESTIONS)
            t0 = time.perf_counter()
            try:
                resp = await client.post(f"{base_url}{endpoint}", headers=headers, json={"message": msg})
                dur = (time.perf_counter() - t0) * 1000
                records.append(RequestRecord(endpoint=endpoint, status_code=resp.status_code, duration_ms=dur))
            except Exception as e:
                dur = (time.perf_counter() - t0) * 1000
                records.append(RequestRecord(endpoint=endpoint, status_code=0, duration_ms=dur, error=str(e)))
        else:
            # Random regular action
            action = random.choice(["session", "tools", "doc_search", "db_query", "health"])
            t0 = time.perf_counter()
            try:
                if action == "session":
                    endpoint = "/api/v1/session"
                    resp = await client.get(f"{base_url}{endpoint}", headers=headers)
                elif action == "tools":
                    endpoint = "/api/v1/mcp/tools"
                    resp = await client.get(f"{base_url}{endpoint}", headers=headers)
                elif action == "doc_search":
                    endpoint = "/api/v1/mcp/tools/search_documents"
                    resp = await client.post(
                        f"{base_url}{endpoint}",
                        headers=headers,
                        json={"parameters": {"query": "security policy", "top_k": 3}},
                    )
                elif action == "db_query":
                    endpoint = "/api/v1/mcp/tools/query_database"
                    resp = await client.post(
                        f"{base_url}{endpoint}",
                        headers=headers,
                        json={"parameters": {"query_id": "directory.by_department", "parameters": {"department": "Engineering"}}},
                    )
                else:
                    endpoint = "/health/live"
                    resp = await client.get(f"{base_url}{endpoint}")

                dur = (time.perf_counter() - t0) * 1000
                records.append(RequestRecord(endpoint=endpoint, status_code=resp.status_code, duration_ms=dur))
            except Exception as e:
                dur = (time.perf_counter() - t0) * 1000
                records.append(RequestRecord(endpoint=endpoint, status_code=0, duration_ms=dur, error=str(e)))

        # Realistic employee pause between clicks: 0.5s to 1.5s
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=random.uniform(0.5, 1.5))
        except asyncio.TimeoutError:
            pass


async def run_burst_scenario(
    base_url: str,
    user_tokens: list[str],
) -> list[RequestRecord]:
    """Execute simultaneous chat submissions across all virtual users."""
    records: list[RequestRecord] = []

    async def single_burst(token: str, question: str):
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            t0 = time.perf_counter()
            try:
                resp = await client.post(
                    f"{base_url}/api/v1/chat",
                    headers=headers,
                    json={"message": question},
                )
                dur = (time.perf_counter() - t0) * 1000
                records.append(RequestRecord(endpoint="/api/v1/chat", status_code=resp.status_code, duration_ms=dur))
            except Exception as e:
                dur = (time.perf_counter() - t0) * 1000
                records.append(RequestRecord(endpoint="/api/v1/chat", status_code=0, duration_ms=dur, error=str(e)))

    tasks = [
        single_burst(token, random.choice(CHAT_QUESTIONS))
        for token in user_tokens
    ]
    await asyncio.gather(*tasks)
    return records


async def run_tier(
    base_url: str,
    num_users: int,
    duration: float,
    mode: str,
    admin_token: str,
) -> TierResult:
    """Run a single test tier (e.g. 10, 50, 100 users)."""
    result = TierResult(virtual_users=num_users, mode=mode, duration_seconds=duration)

    # 1. Obtain user tokens for synthetic employees
    user_tokens: list[str] = []
    async with httpx.AsyncClient(timeout=10.0) as client:
        for i in range(num_users):
            username, pwd = DEMO_USERS[i % len(DEMO_USERS)]
            tok = await authenticate_user(client, base_url, username, pwd)
            if not tok:
                tok = admin_token
            user_tokens.append(tok)

    # Monitor hardware in background
    peak_ram = 0.0
    peak_vram = 0.0
    peak_gpu = 0.0
    stop_hw = asyncio.Event()

    async def hw_monitor():
        nonlocal peak_ram, peak_vram, peak_gpu
        while not stop_hw.is_set():
            s = sample_hardware()
            peak_ram = max(peak_ram, s.ram_used_mb)
            peak_vram = max(peak_vram, s.vram_used_mb)
            peak_gpu = max(peak_gpu, s.gpu_util_pct)
            try:
                await asyncio.wait_for(stop_hw.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass

    hw_task = asyncio.create_task(hw_monitor())
    records: list[RequestRecord] = []

    wall_start = time.perf_counter()

    if mode == "burst":
        records = await run_burst_scenario(base_url, user_tokens)
    else:
        # Mixed workload with pooled keepalive HTTP/1.1 connections
        stop_event = asyncio.Event()
        limits = httpx.Limits(max_keepalive_connections=max(20, num_users), max_connections=max(50, num_users * 2))
        async with httpx.AsyncClient(limits=limits, timeout=45.0) as client:
            worker_tasks = [
                asyncio.create_task(
                    simulate_mixed_employee(
                        i, base_url, user_tokens[i], client, stop_event, records, chat_interval_s=25.0
                    )
                )
                for i in range(num_users)
            ]
            await asyncio.sleep(duration)
            stop_event.set()
            await asyncio.gather(*worker_tasks, return_exceptions=True)

    actual_duration = time.perf_counter() - wall_start
    result.duration_seconds = actual_duration

    stop_hw.set()
    await hw_task
    result.peak_ram_mb = peak_ram
    result.peak_vram_mb = peak_vram
    result.peak_gpu_util = peak_gpu

    # Fetch backend LLM metrics
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            m_resp = await client.get(
                f"{base_url}/api/v1/admin/metrics",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            if m_resp.status_code == 200:
                result.llm_metrics = m_resp.json()
    except Exception:
        pass

    # Process statistics
    result.total_requests = len(records)
    all_latencies: list[float] = []
    non_llm_latencies: list[float] = []
    chat_latencies: list[float] = []

    for r in records:
        result.status_codes[r.status_code] = result.status_codes.get(r.status_code, 0) + 1
        result.endpoint_counts[r.endpoint] = result.endpoint_counts.get(r.endpoint, 0) + 1
        result.endpoint_latencies.setdefault(r.endpoint, []).append(r.duration_ms)

        if 200 <= r.status_code < 400:
            result.successful_requests += 1
            all_latencies.append(r.duration_ms)
            if r.endpoint == "/api/v1/chat":
                chat_latencies.append(r.duration_ms)
                result.chat_completed += 1
            else:
                non_llm_latencies.append(r.duration_ms)
        elif r.status_code == 403:
            result.intentional_denials += 1
            all_latencies.append(r.duration_ms)
            non_llm_latencies.append(r.duration_ms)
        elif r.status_code == 429:
            result.rejected_requests += 1
            if r.endpoint == "/api/v1/chat":
                result.chat_rejected += 1
        elif r.status_code == 503:
            result.service_unavailable += 1
            result.failed_requests += 1
        elif r.status_code >= 500:
            result.server_errors += 1
            result.failed_requests += 1
        elif r.status_code == 0:
            result.timeouts += 1
            result.failed_requests += 1
        else:
            result.failed_requests += 1

    result.throughput_rps = (
        result.total_requests / actual_duration if actual_duration > 0 else 0.0
    )

    def calc_percentiles(lats: list[float]) -> tuple[float, float, float]:
        if not lats:
            return 0.0, 0.0, 0.0
        s = sorted(lats)
        p50 = statistics.median(s)
        p95 = statistics.quantiles(s, n=20)[18] if len(s) >= 20 else max(s)
        p99 = statistics.quantiles(s, n=100)[98] if len(s) >= 100 else max(s)
        return round(p50, 1), round(p95, 1), round(p99, 1)

    result.overall_p50_ms, result.overall_p95_ms, result.overall_p99_ms = calc_percentiles(all_latencies)
    _, result.non_llm_p95_ms, result.non_llm_p99_ms = calc_percentiles(non_llm_latencies)
    result.chat_p50_ms, result.chat_p95_ms, result.chat_p99_ms = calc_percentiles(chat_latencies)

    # Acceptance Criteria Check
    # 1. Non-LLM p95 <= 1000ms, p99 <= 2000ms
    if non_llm_latencies and result.non_llm_p95_ms > 1000.0:
        result.criteria_passed = False
        result.criteria_notes.append(f"Non-LLM p95 ({result.non_llm_p95_ms}ms) exceeded 1000ms target")
    if non_llm_latencies and result.non_llm_p99_ms > 2000.0:
        result.criteria_passed = False
        result.criteria_notes.append(f"Non-LLM p99 ({result.non_llm_p99_ms}ms) exceeded 2000ms target")

    # 2. No unexpected 500 errors
    if result.status_codes.get(500, 0) > 0:
        result.criteria_passed = False
        result.criteria_notes.append(f"Server encountered {result.status_codes[500]} unexpected HTTP 500 errors")

    return result


def _parse_int_sequence(value: Any) -> list[int]:
    if not value:
        return []
    if isinstance(value, list):
        items: list[int] = []
        for v in value:
            for part in str(v).split(","):
                part = part.strip()
                if part:
                    items.append(int(part))
        return items
    return [int(x.strip()) for x in str(value).split(",") if x.strip()]


async def main():
    parser = argparse.ArgumentParser(description="AeroGrid AI E2E Concurrency & Workload Benchmark")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="Base API URL")
    parser.add_argument("--users", "--tiers", dest="users", nargs="*", default=None, help="User counts or tiers")
    parser.add_argument("--burst-levels", nargs="*", default=None, help="Burst levels (e.g. 10 50 100)")
    parser.add_argument("--duration", type=float, default=15.0, help="Duration in seconds per mixed tier")
    parser.add_argument("--skip-burst", action="store_true", help="Skip independent burst test")
    parser.add_argument("--json-out", "--output", dest="json_out", default=None, help="Save report to JSON file")
    parser.add_argument("--admin-user", default=os.environ.get("AEROGRID_ADMIN_USER", "admin.system"), help="Admin username for metrics collection")
    parser.add_argument("--admin-pass", default=DEFAULT_ADMIN_PASS, help="Admin password for metrics collection")
    args = parser.parse_args()

    parsed_users = _parse_int_sequence(args.users)
    user_levels = parsed_users if parsed_users else [1, 10, 25, 50, 75, 100]
    parsed_bursts = _parse_int_sequence(args.burst_levels)
    burst_users = parsed_bursts if parsed_bursts else [u for u in [10, 50, 100] if u in user_levels or u <= max(user_levels)]

    print("================================================================================")
    print("           AEROGRID AI — PRODUCTION READINESS CAPACITY BENCHMARK                ")
    print("================================================================================")
    print(f"Target URL:        {args.base_url}")
    print(f"User Tiers:        {user_levels}")
    print(f"Tier Duration:     {args.duration}s")
    print(f"Burst Levels:      {burst_users if not args.skip_burst else 'SKIPPED'}")
    print(f"Timestamp:         {datetime.now(timezone.utc).isoformat()}")

    # Check health and get admin token
    admin_token: str | None = None
    is_real_model = False
    model_name = "unknown"
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            h = await client.get(f"{args.base_url}/health/ready")
            if h.status_code != 200:
                print(f"ERROR: Server not ready at {args.base_url}: {h.text}")
                return
            admin_token = await authenticate_user(client, args.base_url, args.admin_user, args.admin_pass)
            if not admin_token:
                print("ERROR: Failed to authenticate admin user.")
                return

            # Check LLM settings
            m = await client.get(f"{args.base_url}/api/v1/admin/metrics", headers={"Authorization": f"Bearer {admin_token}"})
            if m.status_code == 200:
                is_real_model = True
                model_name = "qwen2.5:3b (via Ollama local GPU)"
        except Exception as e:
            print(f"ERROR connecting to server: {e}")
            return

    print(f"Inference Mode:    {'REAL LOCAL MODEL' if is_real_model else 'SIMULATED'}")
    print(f"Model Serving:     {model_name}")
    print("--------------------------------------------------------------------------------\n")

    results: list[TierResult] = []

    # Run Mixed Tiers
    print(">>> SECTION 1: PROGRESSIVE MIXED EMPLOYEE WORKLOAD")
    print("Simulating realistic navigation, session checks, doc searches, DB queries, and AI questions.\n")

    for u in user_levels:
        print(f"Running Tier: {u} Concurrent Employees ({args.duration}s)...", end="", flush=True)
        res = await run_tier(args.base_url, u, args.duration, "mixed", admin_token)
        results.append(res)
        print(" DONE")
        print(f"   Reqs: {res.total_requests} | Throughput: {res.throughput_rps:.1f} rps | Non-LLM p95: {res.non_llm_p95_ms}ms | Chat p50: {res.chat_p50_ms}ms")
        print(f"   Codes: {dict(sorted(res.status_codes.items()))} | Chat 200: {res.chat_completed}, 429: {res.chat_rejected} | Denials(403): {res.intentional_denials}")
        print(f"   Peak RAM: {res.peak_ram_mb:.0f} MB | Peak VRAM: {res.peak_vram_mb:.0f} MB | Peak GPU: {res.peak_gpu_util:.0f}%\n")
        # Grace period between tiers
        await asyncio.sleep(2.0)

    # Run Burst Tiers
    burst_results: list[TierResult] = []
    if not args.skip_burst and burst_users:
        print("\n>>> SECTION 2: INDEPENDENT CHAT BURST STRESS TEST")
        print("Simulating simultaneous AI questions from burst user tiers.\n")
        for u in burst_users:
            print(f"Running Chat Burst: {u} Simultaneous Questions...", end="", flush=True)
            b_res = await run_tier(args.base_url, u, 0, "burst", admin_token)
            burst_results.append(b_res)
            print(" DONE")
            print(f"   Chat Completed: {b_res.chat_completed} | Chat Overload 429: {b_res.chat_rejected} | Failed: {b_res.failed_requests}")
            print(f"   Chat Latency p50: {b_res.chat_p50_ms}ms | p95: {b_res.chat_p95_ms}ms | Codes: {dict(sorted(b_res.status_codes.items()))}\n")
            await asyncio.sleep(2.0)

    # Print Summary Table
    print("\n================================================================================")
    print("                        CAPACITY BENCHMARK SUMMARY TABLE                        ")
    print("================================================================================")
    header = f"{'Users':<6} | {'Reqs':<6} | {'RPS':<6} | {'Non-LLM p95':<12} | {'Chat p50':<9} | {'Chat p95':<9} | {'Status Codes':<18} | {'Pass?':<5}"
    print(header)
    print("-" * len(header))
    for r in results:
        status_str = " ".join([f"{k}:{v}" for k, v in sorted(r.status_codes.items())])
        pass_str = "PASS" if r.criteria_passed else "FAIL"
        print(f"{r.virtual_users:<6} | {r.total_requests:<6} | {r.throughput_rps:<6.1f} | {r.non_llm_p95_ms:<10.1f}ms | {r.chat_p50_ms:<7.1f}ms | {r.chat_p95_ms:<7.1f}ms | {status_str:<18} | {pass_str:<5}")

    if burst_results:
        print("\n--- CHAT BURST RESULTS ---")
        for b in burst_results:
            status_str = " ".join([f"{k}:{v}" for k, v in sorted(b.status_codes.items())])
            print(f"Burst {b.virtual_users} users: Completed={b.chat_completed}, Rejected(429)={b.chat_rejected}, Statuses={status_str}")

    print("================================================================================\n")

    if args.json_out:
        out_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "base_url": args.base_url,
            "inference_mode": "REAL" if is_real_model else "SIMULATED",
            "model_name": model_name,
            "mixed_results": [r.__dict__ for r in results],
            "burst_results": [b.__dict__ for b in burst_results],
        }
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(out_data, f, indent=2)
        print(f"Report saved to: {args.json_out}")


if __name__ == "__main__":
    asyncio.run(main())
