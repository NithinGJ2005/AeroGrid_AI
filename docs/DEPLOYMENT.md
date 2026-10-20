# Deployment and Operations Guide

## Overview

This guide defines the production deployment topology for AeroGrid AI serving **50–100 concurrent active employees** using Docker Compose or Podman. The deployment strictly enforces:
1. **Network Isolation**: Outbound blocking on internal and backend networks to guarantee zero data exfiltration and zero external AI calls.
2. **Tiered Edge Reverse Proxy**: Internal TLS termination, endpoint-category rate-limiting for shared corporate egress IPs, and security headers via Nginx.
3. **Least-Privilege Execution**: Non-root container execution (`appuser`, UID 10001) with unprivileged read-only document mounts.
4. **Lightweight & Air-Gapped**: Pre-staged dependencies and local model weights (`qwen2.5:1.5b`), eliminating runtime internet downloads and expensive GPU cluster prerequisites.

---

## 1. Production Topology

```text
[ 50–100 Employee Workstations ]
        │ HTTPS (Port 443 via Corporate NAT Egress IP)
        ▼
[ intranet-reverse-proxy (Nginx) ]
        │ - General API Rate Limit: 100 req/s, burst 150 nodelay
        │ - Auth Login Rate Limit: 5 req/s, burst 10 nodelay
        │ - Chat Rate Limit: 15 req/s, burst 25 nodelay
        │ - Keepalive: 64 persistent upstream connections
        │ Network: internal_app (internal: true)
        ▼
[ intranet-assistant-app (FastAPI / Uvicorn) ]
        │ - Non-blocking async event loop
        │ - In-memory / threadpool MCP tools (Document Search, Database Catalog)
        │ - Bounded admission queue: concurrency=2, depth=10, wait=30s
        │ Network: isolated_backend (internal: true)
        ▼
[ intranet-llm-service (Ollama / vLLM / llama.cpp) ]
  Local weights (e.g. qwen2.5:1.5b Safetensors) mounted read-only at /models
```

---

## 2. Nginx Tiered Rate Limiting Policy

In corporate networks where 50–100 employees share a single office NAT egress IP, a flat 10r/s per-IP rate limit produces false-positive `429` rejections during normal work hours. The reverse proxy in [`deploy/nginx.conf`](file:///d:/MultiAgent/deploy/nginx.conf) applies separate policies per endpoint category:

| Zone | Endpoints | Rate | Burst | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| `general_api_zone` | `/` and standard APIs (`/api/v1/session`, `/api/v1/mcp/tools`, `/static/*`) | **100 req/s** | **150** (nodelay) | Accommodates concurrent navigation, session checks, and asset loading for 50–100 employees sharing an egress IP. |
| `auth_login_zone` | `/api/v1/auth/login`, `/api/v1/auth/token` | **5 req/s** | **10** (nodelay) | Strict protection against automated credential stuffing and brute-force password spraying. |
| `chat_edge_zone` | `/api/v1/chat` | **15 req/s** | **25** (nodelay) | Prevents chat flood denial-of-service at the proxy edge while passing burst traffic to the backend bounded queue. |
| *Bypass* | `/health/live`, `/health/ready` | Unlimited | None | Health checks, readiness probes, and internal monitors bypass edge rate limits. |

Upstream connection reuse is configured with `keepalive 64;` in `upstream assistant_backend`, preventing socket exhaustion during high concurrency.

---

## 3. Network Isolation & Outbound Blocking

The Compose specification declares:
```yaml
networks:
  internal_app:
    driver: bridge
    internal: true
  isolated_backend:
    driver: bridge
    internal: true
```

### Outbound Blocking Validation
When `internal: true` is set on Docker/Podman networks:
- No default gateway to the public internet is attached to the container interfaces.
- Attempts to reach public IPs or external domain names (e.g. `api.openai.com`, `pypi.org`) fail immediately with `Network unreachable` or name resolution failure.
- This provides network-level proof that no prompts, embeddings, or corporate documents can leave the intranet perimeter.

---

## 4. Offline Staging Procedure

In compliance with enterprise air-gap policies, runtime internet access is prohibited:

1. **Stage Dependency Wheels**:
   Execute `./deploy/offline-staging.sh` (or `offline-staging.ps1` on Windows) on an approved build workstation with access to the internal package mirror.
   This places all pinned wheels into `deploy/wheelhouse/`.

2. **Stage Approved Model Weights**:
   Place the license-reviewed, scanned model weights in Hugging Face Safetensors format into `deploy/models/qwen2.5:1.5b` (including `config.json`, `generation_config.json`, `tokenizer.json`, `tokenizer_config.json`, and `model.safetensors`).
   Because Compose resolves relative volumes relative to the directory containing `docker-compose.yml` (`deploy/`), the default volume mapping `- ${INTERNAL_MODEL_PATH:-./models}:/models:ro` resolves `./models` to `deploy/models`. If overriding `INTERNAL_MODEL_PATH`, specify `./models` or an absolute path (never `./deploy/models`).

3. **Deploy with Compose/Podman**:
   ```bash
   cd deploy
   docker compose up -d --build
   ```

---

## 5. Production Configuration Checklist

Before initiating production:
- [ ] Place valid internal CA-signed TLS certificates in `deploy/certs/server.crt` and `deploy/certs/server.key`.
- [ ] Set `SECRET_KEY` in `.env` to a high-entropy secret ($\ge 32$ characters).
- [ ] Ensure `LLM_MODEL=qwen2.5:1.5b` (or internal approved model) has verified licensing (standard staging uses Apache-2.0 `Qwen2.5-1.5B-Instruct`; 3B requires commercial license from Alibaba Cloud).
- [ ] Set `LLM_MAX_CONCURRENT_GENERATIONS=2`, `LLM_MAX_QUEUE_DEPTH=10`, and `LLM_MAX_QUEUE_WAIT_SECONDS=30` for local GPU deployment.
- [ ] Configure `OIDC_ISSUER`, `OIDC_JWKS_URL`, and `AUTH_AUDIENCE` pointing to the corporate Identity Provider (or use durable PBKDF2 local accounts).
- [ ] Populate `ROLE_PERMISSION_MAP` with server-side role assignments.
- [ ] Confirm `DOCUMENT_ROOTS` point to authorized directories containing `.acl.json` files.
- [ ] Verify `LLM_ALLOWED_HOSTS` includes only the internal inference hostname.
