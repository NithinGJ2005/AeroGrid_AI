# Capacity, Observability, and Benchmark Guide

## Overview

This guide documents the capacity baselines, observability architecture, load testing methodology, and empirical benchmark results for AeroGrid AI serving **50–100 concurrent active enterprise employees**.

It clearly differentiates between:
- **Connected Active Employees**: Employees navigating the portal, maintaining authenticated sessions, searching documents, querying approved databases, and asking questions at realistic intervals.
- **Simultaneous LLM Generations**: The subset of requests actively executing matrix multiplication on the GPU at any single moment.

---

## 1. Workload Definition & Concurrency Model

Serving 50–100 active employees **does not** require 50–100 simultaneous LLM generations. In an enterprise workplace:
1. Employees spend the majority of their time reading documentation, viewing dashboards, verifying database records, and formulating inquiries.
2. AI chat questions are submitted intermittently (e.g. every 20–60 seconds per employee), creating a natural staggered workload.
3. Ordinary session checks, navigation, permission-aware document search, and read-only database queries must remain highly responsive (p95 < 1000ms) even while inference is busy.
4. Occasional traffic spikes (e.g. team-wide meetings or all-hands) may produce sudden bursts of simultaneous chat questions. Under such bursts, the system must shed excess load gracefully via structured HTTP 429 responses rather than crashing, exhausting VRAM, or freezing the application event loop.

---

## 2. Test Environment & Hardware Specification

The empirical benchmark was executed directly against the local deployed infrastructure:

| Component | Specification |
| :--- | :--- |
| **Host CPU** | Intel Core i5-11400H (6 cores, 12 logical threads, up to 4.5 GHz) |
| **System RAM** | 8.0 GB DDR4 |
| **Operating System** | Windows 11 Enterprise (NTFS filesystem, single-process Uvicorn ASGI) |
| **Local GPU** | NVIDIA GeForce RTX 2050 Laptop GPU (4.0 GB dedicated GDDR6 VRAM) |
| **Inference Server** | Local Ollama engine (`http://127.0.0.1:11434/v1`) |
| **Benchmark Served Model** | `qwen2.5:3b` (Q4_K_M quantization, 1.9 GB footprint, Qwen Research License Agreement) |
| **GPU Memory Usage** | 2,161 MB peak VRAM (out of 4,096 MB physical capacity) |
| **Admission Limits** | `LLM_MAX_CONCURRENT_GENERATIONS=2`, `LLM_MAX_QUEUE_DEPTH=10`, `LLM_MAX_QUEUE_WAIT_SECONDS=30` |

> [!NOTE]
> **Separation of Native Ollama Benchmarks vs. Staging Deployment**: The load test results below reflect the native Windows Ollama setup running `qwen2.5:3b`. For enterprise staging and production deployment, the deployment configuration is standardized on the Apache-2.0 licensed `qwen2.5:1.5b` checkpoint (`Qwen/Qwen2.5-1.5B-Instruct`). Staging vLLM performance with `qwen2.5:1.5b` will be independently measured during live staging host validation.

---

## 3. Empirical Load Test Results

Load testing was conducted using the end-to-end benchmark utility [`scripts/benchmark_e2e_workload.py`](file:///d:/MultiAgent/scripts/benchmark_e2e_workload.py) using real synthetic employee accounts, real SQLite databases, and the live local `qwen2.5:3b` model.

### Section A: Progressive Mixed Employee Workload

Virtual employees simulated realistic workday behavior: authenticated session checks (`/api/v1/session`), tool discovery (`/api/v1/mcp/tools`), document keyword search with ACL verification (`/api/v1/mcp/tools/search_documents`), approved catalog database queries (`/api/v1/mcp/tools/query_database`), health pings (`/health/live`), and staggered AI questions (`/api/v1/chat`).

| Virtual Users | Total Reqs | Throughput (RPS) | Non-LLM p95 | Chat p50 | Chat p95 | Status Codes | Peak RAM | Peak VRAM | Acceptance Criteria |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1 (Baseline)** | 6 | 0.5 req/s | 6.6 ms | N/A | N/A | `200: 6` | 6,357 MB | 2,161 MB | **PASS** |
| **10** | 69 | 5.5 req/s | 44.9 ms | 3.5 s | 3.5 s | `200: 66, 403: 3` | 6,458 MB | 2,161 MB | **PASS** |
| **25** | 153 | 7.2 req/s | 112.0 ms | 10.0 s | 11.8 s | `200: 143, 403: 10` | 6,587 MB | 2,161 MB | **PASS** |
| **50** | 296 | 7.2 req/s | **232.6 ms** | 19.0 s | 31.4 s | `200: 270, 403: 22, 429: 4` | 6,782 MB | 2,161 MB | **PASS** (Target < 1000ms) |
| **75** | 419 | 8.0 req/s | 1,436.6 ms | 31.4 s | 43.1 s | `0: 1, 200: 377, 403: 33, 429: 8` | 6,941 MB | 2,161 MB | **FAIL** (Non-LLM p95 > 1s) |
| **100** | 508 | 9.6 req/s | 2,020.2 ms | 26.5 s | 41.8 s | `200: 451, 403: 41, 429: 16` | 6,667 MB | 2,161 MB | **FAIL** (Non-LLM p95 > 1s) |

*Note on HTTP 403 responses: Synthetic user `emma.watson` holds the `analyst` role, which does not have `documents:search` permission. The 403 responses demonstrate that permission filtering and authorization checks remain strictly enforced under heavy concurrent load.*

### Section B: Independent Chat Burst Stress Test

To evaluate behavior during traffic spikes without mixing ordinary navigation, simultaneous chat submissions were triggered across all virtual users at the exact same millisecond:

| Simultaneous Chat Submissions | Completed (200 OK) | Shed / Overloaded (429) | Unhandled Failures | Latency p50 | Latency p95 | GPU Stability |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **10 Users** | 10 (100%) | 0 (0%) | 0 | 21.0 s | 28.8 s | 100% stable; 0 VRAM leaks |
| **50 Users** | **12** (24%) | **38** (76%) | 0 | 29.0 s | 38.7 s | 100% stable; 0 VRAM leaks |
| **100 Users** | **12** (12%) | **88** (88%) | 0 | 27.4 s | 40.8 s | 100% stable; 0 VRAM leaks |

**Key Finding**:
The system strictly honors the mathematical capacity limit:
$$\text{Admitted Requests} = \text{max\_concurrent\_generations} (2) + \text{max\_queue\_depth} (10) = 12$$
All requests beyond 12 receive an immediate, structured HTTP 429 `service_overloaded` response. The local GPU remained completely stable at 2,161 MB VRAM without out-of-memory errors or process termination.

---

## 4. Acceptance Criteria Verification Summary

| Criterion | Target | 50-User Result | 100-User Result | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Process Stability** | 0 crashes, 0 deadlocks | 0 crashes, 0 deadlocks | 0 crashes, 0 deadlocks | **PASSED** (both) |
| **Non-LLM p95 Latency** | $\le 1,000\text{ ms}$ | **232.6 ms** (1-worker baseline) / **152.6 ms** (2-worker run) | **2,020.2 ms** (1-worker baseline) / **1,774.5 ms** (2-worker run) | **50: PASS**, 100: FAIL |
| **Non-LLM p99 Latency** | $\le 2,000\text{ ms}$ | **268.1 ms** (1-worker baseline) / **192.2 ms** (2-worker run) | **3,638.1 ms** (1-worker baseline) / **2,597.6 ms** (2-worker run) | **50: PASS**, 100: FAIL |
| **AI Request Reliability** | 200 OK or 429 within deadline | 100% handled | 100% handled | **PASSED** (both) |
| **Security & Isolation** | No ACL leaks, 0 500 errors | 0 leaks, 0 500s | 0 leaks, 0 500s | **PASSED** (both) |

**Empirical Verdict & Readiness Status**:
- **50 Concurrent Active Employees**: **Short-test pass** for the portal API latency target:
  - 1-worker baseline (`benchmark_production_results.json`): non-LLM p95 = **232.6 ms**, non-LLM p99 = **268.1 ms**.
  - 2-worker candidate (`benchmark_results_50users_2workers.json`): non-LLM p95 = **152.6 ms**, non-LLM p99 = **192.2 ms**.
  - 1-worker dedicated verification (`benchmark_results_50users_measured.json`): non-LLM p95 = **249.5 ms**, non-LLM p99 = **272.8 ms**.
  - *All measured strictly against native local Ollama on Windows/NVIDIA RTX 2050; none transferred to vLLM. Staging soak test (2–4 hours) is still required before full production sign-off due to tight host memory headroom (7.6–7.7 GB peak RAM on an 8 GB host).*
- **100 Concurrent Active Employees**:
  - **Local 100-User Benchmark**: **FAILED** against the 1,000 ms non-LLM p95 target for the measured run:
    - 1-worker baseline (`benchmark_production_results.json`): non-LLM p95 = **2,020.2 ms**, non-LLM p99 = **3,638.1 ms**.
    - 1-worker dedicated verification (`benchmark_results_100users_measured.json`): non-LLM p95 = **2,125.1 ms**, non-LLM p99 = **3,704.6 ms**.
    - 2-worker candidate (`benchmark_results_100users_2workers.json`): non-LLM p95 = **1,774.5 ms**, non-LLM p99 = **2,597.6 ms**.
    - *Process stability and security pass with zero crashes or leaks, but portal API latency target fails across all measured local runs.*
  - **Target Docker Compose / Nginx Staging**: **UNVERIFIED** until directly benchmarked on staging infrastructure.

### 4.1 Small-Sample Statistical Limitations & Measurement Methodology

#### A. Verified Progressive Benchmark Results (Local Full Backend)

All requests were verified by source inspection to have been initiated during the active 15-second load window before `stop_event.set()`. The table distinguishes between the **offered request rate** during that window and the **wall-clock throughput** over the full run (including worker drain):

| Virtual Users | Total Requests | Offered Request Rate (15s Window) | Wall-Clock Throughput | Non-LLM p95 | Non-LLM p99 | Chat p50 | Chat p95 | Chat p99 | Status Breakdown |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **10** | 102 | 6.80 req/s | 5.21 req/s | 119.7 ms ($N=96$) | **153.7 ms\*** *(max observed, $N=96 < 100$)* | 4,032.9 ms ($N=6$) | **6,662.1 ms\*** *(max observed, $N=6 < 20$)* | **6,662.1 ms\*** *(max observed, $N=6 < 20$)* | • Expected 403 Denials: **6**<br>• Intentional 429 Sheds: **0**<br>• HTTP 200 OK: **96** (90 portal + 6 chat)<br>• Unexpected 5xx: **0**<br>• Timeouts: **0** |
| **25** | 244 | 16.27 req/s | 6.19 req/s | 98.3 ms ($N=233$) | **460.3 ms** ($N=233$) | 24,141.1 ms ($N=11$) | **28,253.8 ms\*** *(max observed, $N=11 < 20$)* | **28,253.8 ms\*** *(max observed, $N=11 < 20$)* | • Expected 403 Denials: **17**<br>• Intentional 429 Sheds: **0**<br>• HTTP 200 OK: **227** (216 portal + 11 chat)<br>• Unexpected 5xx: **0**<br>• Timeouts: **0** |
| **50** | 504 | 33.60 req/s | 11.11 req/s | 155.8 ms ($N=479$) | **205.6 ms** ($N=479$) | 25,173.8 ms ($N=14$) | **33,541.3 ms\*** *(max observed, $N=14 < 20$)* | **33,541.3 ms\*** *(max observed, $N=14 < 20$)* | • Expected 403 Denials: **35**<br>• Intentional 429 Sheds: **11**<br>• HTTP 200 OK: **458** (444 portal + 14 chat)<br>• Unexpected 5xx: **0**<br>• Timeouts: **0** |

*\* Denotes fallback values: Under the benchmark's configured small-sample fallback policy, percentiles are explicitly substituted with the sample maximum observed latency when sample count is below the configured threshold ($N < 20$ for p95, $N < 100$ for p99).*

#### B. Benchmark Small-Sample Fallback Policy
Python's standard library `statistics.quantiles()` does not automatically replace small-sample percentiles with the maximum. The benchmark utility ([`scripts/benchmark_e2e_workload.py`](file:///d:/MultiAgent/scripts/benchmark_e2e_workload.py#L385-L393)) explicitly implements this fallback policy:
```python
p95 = statistics.quantiles(s, n=20)[18] if len(s) >= 20 else max(s)
p99 = statistics.quantiles(s, n=100)[98] if len(s) >= 100 else max(s)
```
Consequently, when sample sizes fall below these thresholds ($N < 20$ for p95, $N < 100$ for p99), the reported values represent **maximum observed latency** rather than statistical percentile estimates.

#### C. Statistical Limitations Disclosure
- **Non-LLM API latency**: The benchmark recorded 96, 233, and 479 qualifying latency samples at the 10-, 25-, and 50-user tiers, respectively. The 10-user sample ($N=96$) does not meet the benchmark's stated minimum of 100 observations for reporting p99, triggering the fallback to maximum observed latency. More generally, these sample counts do not by themselves establish statistical confidence; reported percentile values should be interpreted as empirical measurements from the tested runs, not as definitive production latency guarantees.
- **Chat latency**: The benchmark recorded only 6, 11, and 14 completed chat requests across the three tiers. Since each tier has fewer than 20 completed chat samples, the benchmark's configured fallback reports the maximum observed latency in place of p95 and p99. These values should therefore be labelled maximum observed chat latency, not treated as reliable percentile estimates. The results are useful for identifying latency under this particular short test, but a longer run is needed for a more representative chat-latency distribution.
- **Expected access denials and load shedding**: Across the runs, HTTP 403 responses (6 at 10u, 17 at 25u, 35 at 50u) are classified as expected authorization denials for the specified analyst-role access attempts on protected document searches. HTTP 429 responses (11 at 50u) are classified as intentional admission-control rejections triggered when the chat queue capacity limit was reached. These outcomes are distinct from unexpected HTTP 5xx errors, but they remain visible in capacity and access-control reporting.

#### D. Sample Count Reconciliation Across Tiers
Qualifying non-LLM latency samples include all completed requests across non-LLM endpoints (`/health/live`, `/api/v1/session`, `/api/v1/mcp/tools`, `/api/v1/mcp/tools/search_documents`, `/api/v1/mcp/tools/query_database`), encompassing both HTTP 200 OK responses and expected HTTP 403 access denials:
- **10-User Tier**: 96 non-LLM samples (90 200 OK + 6 403 Forbidden) + 6 chat samples (200 OK) = 102 total requests. Wall-clock throughput = 5.21 req/s (102 reqs / 19.59s).
- **25-User Tier**: 233 non-LLM samples (216 200 OK + 17 403 Forbidden) + 11 chat samples (200 OK) = 244 total requests. Total HTTP 200s = 216 + 11 = 227. Wall-clock throughput = 6.19 req/s (244 reqs / 39.42s).
- **50-User Tier**: 479 non-LLM samples (444 200 OK + 35 403 Forbidden) + 14 completed chat samples (200 OK) + 11 rejected chat samples (429) = 504 total requests. Total HTTP 200s = 444 + 14 = 458. Wall-clock throughput = 11.11 req/s (504 reqs / 45.35s).

---

## 5. Scale-Up & Hardware Upgrade Path

To safely scale from 50 to 100+ concurrent active employees while maintaining non-LLM latency under 1 second:

1. **Two-Worker Staging Configuration**:
   Deploy 2 Uvicorn worker processes behind Nginx (`deploy/nginx.conf` and `deploy/docker-compose.yml`). On an 8 GB RAM host, 2 workers is the safe ceiling to prevent OS paging and memory exhaustion while halving per-worker queue depth (`max_in_flight=1`, `max_queue_depth=5` per worker, totaling 2 active and 10 queued requests). Do not run 4 workers on an 8 GB host.
2. **Dedicated Inference Gateway**:
   As organizational demand expands, migrate local Ollama inference to an internal dedicated inference server:
   - **Recommended Initial Dedicated Sizing**: 1x NVIDIA L4 (24GB VRAM) or RTX 4090 (24GB VRAM) running vLLM with continuous batching.
   - **Recommended Concurrency**: Increase `LLM_MAX_CONCURRENT_GENERATIONS` to 8–16 and `LLM_MAX_QUEUE_DEPTH` to 40.
3. **No Application Rewrites Required**:
   Because `LocalLLMClient` conforms to standard OpenAI-compatible endpoints (`/v1/chat/completions`), scaling to vLLM, TensorRT-LLM, or larger models (e.g. Qwen 2.5 14B / 32B or Llama 3.1 8B) requires changing only `LLM_BASE_URL` and `LLM_MODEL` in `.env`.

---

## 6. How to Run the Benchmarks

### A. Synthetic In-Process Benchmark (Fast Mock)
```bash
python scripts/benchmark_capacity.py --concurrency 8 --requests 40
```

### B. Real End-to-End Progressive Benchmark (Live Model)
Ensure Uvicorn and Ollama are running, then execute:
```bash
python scripts/benchmark_e2e_workload.py --base-url http://127.0.0.1:8000 --users 1,10,25,50,75,100 --duration 15 --json-out benchmark_results.json
```
