# Local LLM Operations Guide

## 1. Serving Boundary & Architecture

The AeroGrid AI backend communicates exclusively with an internal, OpenAI-compatible inference endpoint:
- **Contract**: `POST {LLM_BASE_URL}/chat/completions` conforming to standard OpenAI ChatCompletions schema.
- **Network Boundary**: Strict SSRF protection enforces that `LLM_BASE_URL` must resolve to a hostname explicitly listed in `LLM_ALLOWED_HOSTS` (e.g. `127.0.0.1`, `localhost`, or internal cluster DNS). No external API calls (OpenAI, Gemini, Anthropic) are permitted. `LLM_INTERNAL_ONLY=true` is enforced at runtime.
- **Asynchronous Execution**: Ingestion and LangGraph orchestration use native async I/O (`LocalLLMClient.agenerate` and `anyio.to_thread.run_sync` tool execution). Active inference never freezes the FastAPI event loop, ensuring health checks and non-LLM endpoints respond in under 50ms.

---

## 2. Recommended Initial Model & Hardware Sizing

### Initial Lightweight Deployment (Verified on Local Hardware)
For immediate deployment on standard workstation/laptop hardware without requiring dedicated multi-GPU servers:

| Property | Value |
| :--- | :--- |
| **Staging Model (Default)** | `qwen2.5:1.5b` (`Qwen/Qwen2.5-1.5B-Instruct`, pinned revision `989aa7980e4cf806f80c7fef2b1adb7bc71aa306`) |
| **License** | **Apache 2.0** (Commercially cleared for enterprise staging & production) |
| **Format** | Hugging Face Safetensors (pinned vLLM `v0.6.3` native engine) or AWQ variant |
| **Memory Footprint** | ~3.08 GB BF16 / ~1.6 GB AWQ |
| **Alternative Evaluation Model** | `qwen2.5:3b` (Qwen Research License Agreement; non-commercial research/evaluation only without Alibaba commercial grant; native Windows Ollama tested) |
| **Hardware Tested** | NVIDIA GeForce RTX 2050 (4GB VRAM), Intel i5-11400H, 8GB RAM |
| **Measured Peak VRAM** | 2,161 MB (well within 4,096 MB physical budget) |
| **Warm Generation Time** | 0.28s to 0.45s for typical short intranet queries |

> [!IMPORTANT]
> Model weights and tokenizers must be pre-staged on local disk or internal registry. The application startup sequence never downloads external model weights.

---

## 3. Capacity Controls & Bounded Admission

The backend implements bounded admission control (`BoundedAdmission` in `app/llm/service.py`) configured via environment variables:

| Variable | Recommended Initial Value | Purpose |
| :--- | :--- | :--- |
| `LLM_MAX_CONCURRENT_GENERATIONS` | `2` | Maximum generations executing matrix multiplication on the GPU simultaneously. |
| `LLM_MAX_QUEUE_DEPTH` | `10` | Maximum requests permitted to wait in the asyncio condition queue. |
| `LLM_MAX_QUEUE_WAIT_SECONDS` | `30` | Maximum time a queued request waits before shedding with HTTP 429. |
| `LLM_REQUEST_TIMEOUT_SECONDS` | `60` | Hard timeout for generation HTTP calls. |
| `LLM_MAX_OUTPUT_TOKENS` | `512` | Restricts runaway generation to conserve GPU memory and execution time. |
| `LLM_CONTEXT_BUDGET_TOKENS` | `4096` | Bounds prompt context and input token allocation. |

### Mathematical Admission Limit:
$$\text{Max In-Flight} + \text{Max Queue} = 2 + 10 = 12 \text{ Active In-Flight + Queued}$$
Any request arriving when 12 requests are active/queued receives an immediate HTTP 429 response with client-safe message:
```json
{
  "error": "service_overloaded",
  "message": "The assistant service is currently at capacity. Please try again shortly.",
  "request_id": "9b12a8f0-1234-4a56-b789-0123456789ab"
}
```

---

## 4. Serving 50–100 Concurrent Employees

1. **Active Employees vs Active Generations**:
   - 50–100 concurrent employees navigating the portal produces ~5–10 requests/second of ordinary traffic (sessions, permissions, tools, doc search, DB queries) and intermittent chat submissions (~1 query per 20–30s per user).
   - Under this representative workload, the 2-generation bounded queue handles regular traffic smoothly with non-LLM latency p95 < 250ms.
2. **Graceful Behavior Under Traffic Spikes**:
   - During sudden surges (e.g. 50 or 100 simultaneous questions), the queue admits 12 requests and sheds the excess via structured 429 responses.
   - The GPU never runs out of VRAM, the backend process does not crash, and health checks continue responding.
3. **Availability of Non-LLM Services**:
   - If the inference service is busy, overloaded (429), or temporarily down (503), all other portal features remain fully operational:
     - Document search (`/api/v1/mcp/tools/search_documents`) continues to return authorized excerpts and citations.
     - Database queries (`/api/v1/mcp/tools/query_database`) continue to return approved catalog results.
     - Session checks (`/api/v1/session`) and audit tracking function uninterrupted.

---

## 5. Enterprise Scale-Up & Model Upgrade Path

When infrastructure budget permits scaling to larger parameter models or higher concurrent employee volumes:

```
+-----------------------------------------------------------------------------------+
| Lightweight Local (Today)                                                         |
| - Model: qwen2.5:1.5b (Apache 2.0 Safetensors on vLLM; 3b Ollama where authorized) |
| - GPU: 1x 4GB VRAM (RTX 2050 / RTX 3050)                                          |
| - Target: 50 concurrent active employees (2 concurrent generations, queue 10)      |
+-----------------------------------------------------------------------------------+
                                         |
                                         v
+-----------------------------------------------------------------------------------+
| Dedicated Enterprise Node (Scale-Up Path)                                         |
| - Model: Qwen 2.5 14B / 32B or Llama 3.1 8B (AWQ / FP16)                          |
| - Serving Engine: vLLM with PagedAttention and continuous batching                |
| - GPU: 1x NVIDIA L4 (24GB) or 1x NVIDIA A100 (80GB)                               |
| - Target: 100–500 concurrent employees (16–32 concurrent generations, queue 64)   |
+-----------------------------------------------------------------------------------+
```

### Transition Steps (Zero Code Changes):
1. Deploy vLLM on dedicated inference server:
   ```bash
   python -m vllm.entrypoints.openai.api_server \
       --model /models/Qwen2.5-14B-Instruct-AWQ \
       --host 0.0.0.0 --port 8000 \
       --max-model-len 4096 \
       --gpu-memory-utilization 0.90
   ```
2. Update `.env` in AeroGrid AI:
   ```env
   LLM_BASE_URL=http://vllm-cluster.internal:8000/v1
   LLM_ALLOWED_HOSTS=["vllm-cluster.internal"]
   LLM_MODEL=Qwen2.5-14B-Instruct-AWQ
   LLM_MAX_CONCURRENT_GENERATIONS=16
   LLM_MAX_QUEUE_DEPTH=50
   ```
3. Restart application workers. No changes to LangGraph, MCP tools, or core application logic are required.
