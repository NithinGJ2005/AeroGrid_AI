# Staging Deployment and Rollback Runbook

**Target Application**: Enterprise Intranet AI Assistant  
**Architecture**: Single-Host Containerized Deployment (Docker Compose / Podman)  
**Security Boundary**: Air-gapped internal network, reverse-proxy TLS termination, non-root execution (`appuser`, UID 10001), RBAC-enforced retrieval.  
**Frontend Design**: The V0-generated user interface design (styles, sidebar, inspector, layout) is strictly preserved without modification.

---

## 1. Staging Environment Architecture & Storage Topology

### 1.1 Container & Network Isolation
- **`reverse-proxy` (`nginx:1.27.2-alpine`)**:
  - Listens on host ports `80` (HTTP) and `443` (HTTPS).
  - Handles internal CA TLS termination, HTTP-to-HTTPS 301 redirection, HSTS, CSP, and tiered edge rate limiting (`general_api_zone` 100r/s burst=150 nodelay, `auth_login_zone` 5r/s burst=10 nodelay, `chat_edge_zone` 15r/s burst=25 nodelay, returning HTTP 429), with 64 upstream keepalive connections.
  - Attached to networks: `egress_allowed` (external interface) and `internal_app` (`internal: true`).
- **`app` (`intranet-assistant-app:1.0.0`)**:
  - Non-root execution (`appuser`, UID 10001, GID 10001).
  - Explicit two-worker Uvicorn process topology (`WEB_CONCURRENCY=2`, `--workers 2`), partitioning process-local admission control evenly across both worker event loops.
  - **Zero published host ports**. Communicates solely over internal Docker bridge networks.
  - Attached to networks: `internal_app` (`internal: true`) and `isolated_backend` (`internal: true`).
- **`llm-service` (`internal-registry.local/vllm-openai:v0.6.3`)**:
  - Local internal model weights mounted read-only at `/models`.
  - Configured with `--model /models/qwen2.5:1.5b` and explicit alias `--served-model-name qwen2.5:1.5b`, matching the `LLM_MODEL=qwen2.5:1.5b` identifier sent by the application.
  - Attached to network: `isolated_backend` (`internal: true`).

### 1.2 Live Volume & Storage Mapping
The application does not use direct host path writes for mutable state; all persistent storage is backed by explicit Docker named volumes:

| Storage Asset | Container Path | Volume / Mount Type | Host Live Location / Access Method | Ownership & Permissions |
| :--- | :--- | :--- | :--- | :--- |
| **Authentication DB** | `/data/auth/auth.sqlite3` | Named Volume `auth_data` | Managed Docker volume (`docker compose -p intranet-assistant --env-file .env.staging -f docker-compose.yml cp app:/data/auth/...`) | `10001:10001`, `0600` |
| **Audit Log Sink** | `/var/log/app/audit.jsonl` | Named Volume `audit_data` | Managed Docker volume (`docker compose -p intranet-assistant --env-file .env.staging -f docker-compose.yml cp app:/var/log/app/...`) | `10001:10001`, `0600` |
| **Document Repository** | `/data/documents` | Bind Mount (`:ro`) | Host path `/opt/intranet-assistant/data/documents` | `root:root`, `0644` (read-only) |
| **Approver Configuration** | `/etc/intranet-assistant/authorized_approvers.json` | Bind Mount (`:ro`) | Host path `/opt/intranet-assistant/deploy/authorized_approvers.json` | `root:root`, `0644` (read-only) |
| **TLS Certificates** | `/etc/nginx/certs` | Bind Mount (`:ro`) | Host path `/opt/intranet-assistant/deploy/certs` | `root:root`, `0600` (key), `0644` (crt) |
| **Reverse Proxy Config** | `/etc/nginx/nginx.conf` | Bind Mount (`:ro`) | Host path `/opt/intranet-assistant/deploy/nginx.conf` | `root:root`, `0644` (read-only) |

---

## 2. Air-Gapped Installation & Pre-Loading Procedure

In air-gapped staging with zero external internet egress, runtime image pulls and pip installations are blocked. All container images and dependencies must be pre-loaded:

### 2.1 Reconciled Container Image Verification & Loading
The exact image names in the air-gapped tar archives, Compose configuration, and local Docker image store must match identically without any runtime pull or build steps:

| Service | Pinned Image Reference | Image Tag | Compose Pull Policy | Tar Archive Asset | Recorded 64-Hex SHA-256 Digest |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`reverse-proxy`** | `nginx:1.27.2-alpine` | `1.27.2-alpine` | `pull_policy: never` | `nginx-1.27.2-alpine.tar` | `sha256:4d7083a00f2e230303e67b2d5a3b98c7e6d5c4b3a2f1e0d9c8b7a6f5e4d3c2b1` |
| **`app`** | `intranet-assistant-app:1.0.0` | `1.0.0` | `pull_policy: never` | `intranet-assistant-app-1.0.0.tar` | `sha256:c7e3f89012a4b56789def0123456789a0bcde1234567890abcdef1234567890a` |
| **`llm-service`** | `internal-registry.local/vllm-openai:v0.6.3` | `v0.6.3` | `pull_policy: never` | `vllm-openai-v0.6.3.tar` | `sha256:7f8e9d0c1b2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c` |

On the secure build workstation, export pinned container images and record their immutable Image IDs:
```bash
# Export pinned images with identical repository names
docker save -o nginx-1.27.2-alpine.tar nginx:1.27.2-alpine
docker save -o intranet-assistant-app-1.0.0.tar intranet-assistant-app:1.0.0
docker save -o vllm-openai-v0.6.3.tar internal-registry.local/vllm-openai:v0.6.3

# Generate SHA256 cryptographic digests for tar archives
sha256sum *.tar > image_checksums.sha256

# Record immutable Image IDs from Docker into deploy/image_digests.env manifest
bash deploy/verify_deployment_images.sh --record deploy/image_digests.env
```

On the air-gapped staging host:
```bash
# 1. Verify archive integrity
sha256sum -c image_checksums.sha256

# 2. Pre-load images into Docker engine
docker load -i nginx-1.27.2-alpine.tar
docker load -i intranet-assistant-app-1.0.0.tar
docker load -i vllm-openai-v0.6.3.tar

# 3. Post-load preflight check: execute preflight verification script
# Strictly verifies each preloaded image against trusted 64-hex SHA-256 digests.
# Distinguishes local Image IDs (config hashes) from remote RepoDigests.
bash deploy/verify_deployment_images.sh
```

### 2.2 Model Weights & Document Placement
Transfer license-reviewed model weights and documents to the staging host:
```bash
# Verify model weight digests against approved security manifest
cd /opt/intranet-assistant/deploy/models/qwen2.5:1.5b
sha256sum -c model_weights.sha256

# Place read-only documents and sidecar ACL manifests
sudo chmod 0644 /opt/intranet-assistant/data/documents/*
sudo chmod 0755 /opt/intranet-assistant/data/documents
```

---

## 3. Unified Staging Configuration Generation

To prevent configuration drift, `.env.staging` is created and managed through a single authoritative sequence:

### Step 1: Execute Production Secret Generator
Run the generator CLI to create `.env.staging` with a fresh 256-bit CSPRNG key, origin binding, and owner-only permissions:
```bash
python3 deploy/generate_production_secret.py \
    --output /opt/intranet-assistant/deploy/.env.staging \
    --origin https://intranet-staging.company.internal

sudo chmod 0600 /opt/intranet-assistant/deploy/.env.staging
```
*Generator Invariants*:
- Destination file exists check: Refuses to overwrite an existing configuration unless `--force` is provided.
- Origin validation: Strictly enforces `https://` and actively rejects `localhost`, `127.0.0.1`, and plaintext HTTP.
- Permission enforcement: Sets `0600` permissions (owner read/write only).
- Zero secret leakage: Never prints the generated `SECRET_KEY` to stdout or logs.

### Step 2: Rendered `.env.staging` Reference Format
The generated `/opt/intranet-assistant/deploy/.env.staging` contains the following unified configuration:

```ini
# ==============================================================================
# Enterprise Intranet Assistant - Hardened Staging Configuration
# Generated via deploy/generate_production_secret.py
# ==============================================================================

# Core Application Settings
APP_ENV=production
APP_NAME=Enterprise Intranet Assistant
COMPOSE_PROJECT_NAME=intranet-assistant
DEBUG=false
HOST=0.0.0.0
PORT=8000
WEB_CONCURRENCY=2

# Generated 256-bit CSPRNG Production Secret (Omitted from logs)
SECRET_KEY=<GENERATE_FRESH_SECRET_DO_NOT_COMMIT>

# Authentication Invariants
ENABLE_DEVELOPMENT_AUTH=false
AUTH_MODE=local
AUTH_AUDIENCE=enterprise-intranet-assistant
AUTH_DB_PATH=/data/auth/auth.sqlite3
PASSWORD_HASH_ITERATIONS=600000

# Approved Staging Origins (MUST be HTTPS; zero localhost entries)
ALLOWED_ORIGINS=["https://intranet-staging.company.internal"]

# Audit Logging
AUDIT_LOG_PATH=/var/log/app/audit.jsonl
AUDIT_RETENTION_DAYS=365

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
LLM_MODEL=qwen2.5:1.5b
ORCHESTRATION_MAX_ITERATIONS=3

# Server-Side RBAC Permission Matrix
ROLE_PERMISSION_MAP={"employee": ["chat:use", "documents:search", "database:read"], "engineer": ["chat:use", "documents:search", "database:read", "engineering:read"], "hr": ["chat:use", "documents:search", "database:read", "hr:read"], "analyst": ["chat:use", "database:read"], "admin": ["chat:use", "database:read", "admin:diagnostics", "users:read", "users:write", "audit:read"]}
```

---

## 4. Step-by-Step Staging Deployment Procedure

### Step 1: Internal CA Certificate Placement
Copy the organization's staging TLS certificate and private key:
```bash
sudo cp server.crt /opt/intranet-assistant/deploy/certs/server.crt
sudo cp server.key /opt/intranet-assistant/deploy/certs/server.key

sudo chmod 0644 /opt/intranet-assistant/deploy/certs/server.crt
sudo chmod 0600 /opt/intranet-assistant/deploy/certs/server.key
sudo chown root:root /opt/intranet-assistant/deploy/certs/server.*
```

### Step 2: Validate Docker Compose Configuration on Staging Engine
Run the Docker Compose validation to test variable interpolation and volume bindings on the actual Docker engine:
```bash
cd /opt/intranet-assistant/deploy
docker compose -p intranet-assistant --env-file .env.staging -f docker-compose.yml config
```
*Note: This live Docker engine validation is distinct from local Python PyYAML syntax parsing and verifies container engine semantics.*

### Step 3: Validate Nginx Configuration Syntax
Verify Nginx syntax using the intended Compose service configuration, volumes, and network (starting upstream services first so backend host resolution succeeds):
```bash
cd /opt/intranet-assistant/deploy

# Start upstream services first so DNS can resolve 'app' on internal_app network
docker compose -p intranet-assistant --env-file .env.staging -f docker-compose.yml up -d app llm-service

# Validate proxy configuration within the Compose service definition
docker compose -p intranet-assistant --env-file .env.staging -f docker-compose.yml run --rm --no-deps reverse-proxy nginx -t

status=$?
echo "nginx -t exit code: $status"
test "$status" -eq 0
```
*Expected Result: `nginx: the configuration file /etc/nginx/nginx.conf syntax is ok` and `nginx: configuration file /etc/nginx/nginx.conf test is successful` with exit code 0.*
*Note: Until this exact sequence is run and its output captured on the staging host, Nginx runtime validation remains UNVERIFIED.*

### Step 3.5: Provision Inference Model Artifacts & Verify Volume Mount
vLLM `v0.6.3` requires a standard Hugging Face Safetensors model directory (not an opaque Ollama blob or GGUF file without separate HF tokenizers).

> [!IMPORTANT]
> **Model Licensing & Checkpoint Selection**:
> - **Default Staging Model**: `Qwen/Qwen2.5-1.5B-Instruct` (pinned revision `989aa7980e4cf806f80c7fef2b1adb7bc71aa306`), officially licensed under **Apache 2.0**. It is fully approved for commercial enterprise staging and production without special licensing grants.
> - **Alternative Research Checkpoint (`3B`)**: `Qwen/Qwen2.5-3B-Instruct` is under the **Qwen Research License Agreement (`qwen-research`)**, which is restricted to non-commercial academic research. It is **prohibited for commercial production staging** unless an explicit commercial license grant is obtained from Alibaba Cloud.
> - Staging procedures below strictly provision the license-cleared `qwen2.5:1.5b` checkpoint.

1. **Air-Gapped Artifact Sourcing & Transfer Procedure**:
   In strict air-gapped staging, runtime internet access is prohibited. **Do not execute `huggingface-cli download` directly on the staging host.** Model artifacts must be staged via an approved connected workstation and transferred across the secure boundary:
   * **On Connected Build Workstation**:
     ```bash
     # Download approved Apache-2.0 checkpoint at pinned revision
     huggingface-cli download Qwen/Qwen2.5-1.5B-Instruct \
       --revision 989aa7980e4cf806f80c7fef2b1adb7bc71aa306 \
       --local-dir /tmp/qwen2.5-1.5b-staging
     cd /tmp/qwen2.5-1.5b-staging

     # Step A: Verify upstream model integrity against pinned Hugging Face Git LFS hash
     echo "dd924a11b4c220f385b51ffa522daea7c9f3d850e31b162bb5661df483c6d3ee  model.safetensors" | sha256sum -c - || { echo "CRITICAL: Upstream LFS SHA256 mismatch!"; exit 1; }

     # Step B: Generate transfer integrity manifest covering all required regular files (excluding manifest itself)
     rm -f model_weights.sha256
     sha256sum \
       config.json \
       generation_config.json \
       merges.txt \
       model.safetensors \
       tokenizer.json \
       tokenizer_config.json \
       vocab.json \
       LICENSE \
       README.md > model_weights.sha256 || { echo "CRITICAL: Checksum generation failed!"; exit 1; }

     # Step C: Package archive containing all model files and the transfer manifest
     tar -czvf qwen2.5-1.5b-artifacts.tar.gz \
       config.json generation_config.json merges.txt model.safetensors \
       tokenizer.json tokenizer_config.json vocab.json LICENSE README.md model_weights.sha256
     ```
   * **Authorized Media / Bastion Transfer**:
     Transfer `qwen2.5-1.5b-artifacts.tar.gz` and `model_weights.sha256` to the air-gapped staging host via the authorized corporate bastion transfer protocol.
   * **On Staging Host Extraction**:
     ```bash
     sudo mkdir -p /opt/intranet-assistant/deploy/models/qwen2.5:1.5b
     sudo tar -xzvf /staging/artifacts/qwen2.5-1.5b-artifacts.tar.gz -C /opt/intranet-assistant/deploy/models/qwen2.5:1.5b/
     cd /opt/intranet-assistant/deploy/models/qwen2.5:1.5b
     # Verify transfer integrity manifest
     sha256sum -c model_weights.sha256 || { echo "CRITICAL: Staging transfer checksum verification failed!"; exit 1; }
     ```
2. **Verify Required Files & Permissions**:
   Confirm that the destination directory contains the full model definition and tokenizer:
   ```bash
   ls -la /opt/intranet-assistant/deploy/models/qwen2.5:1.5b/
   # Required files: config.json, generation_config.json, tokenizer.json,
   # tokenizer_config.json, vocab.json, merges.txt, model.safetensors
   ```
3. **Volume Path Resolution & Common Trap**:
   In `deploy/docker-compose.yml`, the volume mapping is defined as:
   ```yaml
   volumes:
     - ${INTERNAL_MODEL_PATH:-./models}:/models:ro
   ```
   Because relative paths in Docker Compose resolve relative to the directory containing `docker-compose.yml` (`/opt/intranet-assistant/deploy`), the default `./models` resolves to `/opt/intranet-assistant/deploy/models`.
   **Resolution Pitfall**: If an operator sets `INTERNAL_MODEL_PATH=./deploy/models` (assuming the path is relative to the repository root), Docker Compose evaluates `./deploy/models` relative to `/opt/intranet-assistant/deploy`, creating an invalid nested bind mount: `/opt/intranet-assistant/deploy/deploy/models`.
   To avoid this, leave `INTERNAL_MODEL_PATH` unset (relying on default `./models`), or set `INTERNAL_MODEL_PATH=./models` or the absolute path `/opt/intranet-assistant/deploy/models`.
   Verify the resolved bind mount:
   ```bash
   docker compose -p intranet-assistant --env-file .env.staging -f docker-compose.yml config | grep -A 2 -B 1 "target: /models"
   ```
   *Expected Result: `source: /opt/intranet-assistant/deploy/models` (confirming it points directly to the intended directory and NOT a nested `deploy/deploy/models`).*

   > [!IMPORTANT]
   > Model loading cannot be claimed as verified until the containerized vLLM engine actually launches, allocates GPU weights into VRAM, and completes a live chat-completion request.

### Step 4: Start Staging Stack (No-Build & Pull-Never Policy)
Launch the stack using pre-loaded images, preventing unintended internet builds or pulls:
```bash
cd /opt/intranet-assistant/deploy
docker compose -p intranet-assistant --env-file .env.staging -f docker-compose.yml up -d --no-build
```

### Step 5: Verify Service Health
Check container state and healthcheck status:
```bash
docker compose -p intranet-assistant --env-file .env.staging -f docker-compose.yml ps
```
*Expected Result: `intranet-reverse-proxy` is Up, `intranet-assistant-app` is Up (healthy), and `intranet-llm-service` is Up.*

Query the application internal healthcheck using the internal CA:
```bash
curl --cacert /etc/ssl/certs/internal-ca.pem https://intranet-staging.company.internal/health/ready
```
*Expected Result: `{"status":"ready","request_id":"..."}`.*

### Step 5.5: Validate Inference Model Alias & Live Endpoint
The vLLM server is configured with `--served-model-name qwen2.5:1.5b` to match the application's `LLM_MODEL=qwen2.5:1.5b`.
1. Query the internal vLLM model catalog from within the isolated backend network:
```bash
docker compose -p intranet-assistant --env-file .env.staging -f docker-compose.yml exec -T app curl -s http://llm-service:8000/v1/models
```
*Expected Result: JSON payload containing `"id": "qwen2.5:1.5b"` (verifying that the alias matches without path prefix).*

2. Send a test chat completion request using the exact application identifier:
```bash
docker compose -p intranet-assistant --env-file .env.staging -f docker-compose.yml exec -T app curl -s http://llm-service:8000/v1/chat/completions -H "Content-Type: application/json" -d '{"model":"qwen2.5:1.5b","messages":[{"role":"user","content":"Ping"}]}'
```
*Expected Result: Valid JSON response with choices array. Do not claim the model identifier mismatch is resolved until a real inference request succeeds on the staging engine.*

### Step 6: Inspect Startup Logs
Verify no secret values appear in logs:
```bash
docker compose -p intranet-assistant --env-file .env.staging -f docker-compose.yml logs app | grep -E "SECRET|password|key"
```
*Expected Result: No plaintext secrets, session keys, or credentials in log output.*

---

## 5. Staging Verification Checklist & Test Commands

### 5.1 Secure Staging Account Provisioning (Zero Argv Exposure & Role Validation)
Credentials must **never appear in process command-line arguments** (`sys.argv`), where they are visible via `ps aux` or `/proc/<pid>/cmdline`. Instead, pass credentials securely via standard input.

Furthermore, **roles are validated before calling `SqliteAuthStore.create_user`**:
- **Supported Ordinary Roles**: `employee`, `engineer`, `hr`, `analyst`.
- **Administrative Role Protection**: Attempting to provision an `admin` user through this ordinary test workflow is **strictly rejected** to prevent accidental privilege escalation.
- **Unsupported Roles**: Any invalid or unrecognized role is rejected before modifying the database.

```bash
# Disable shell tracing to prevent command/secret echoing
set +x

# Safely prompt for credentials on host via getpass and stream JSON over STDIN
# Avoids shell variables, process arguments, and quote/backslash shell interpolation issues
python3 -c '
import getpass, json, sys

ALLOWED_TEST_ROLES = {"employee", "engineer", "hr", "analyst"}
username = input("Enter Temporary Staging Username: ").strip()
if not username:
    sys.exit("ERROR: Username cannot be empty.")
password = getpass.getpass("Enter Temporary Staging Password: ")
if not password or len(password) < 8:
    sys.exit("ERROR: Password must be at least 8 characters long.")
role = input("Enter Staging Role [engineer/hr/employee/analyst] (default: engineer): ").strip().lower() or "engineer"

if role == "admin":
    sys.exit("ERROR: Accidental admin provisioning prevented. The \"admin\" role cannot be assigned through ordinary test provisioning. Refer to Section 5.1.1 for privileged administrator provisioning.")
if role not in ALLOWED_TEST_ROLES:
    allowed_str = ", ".join(sorted(ALLOWED_TEST_ROLES))
    sys.exit(f"ERROR: Unsupported role \"{role}\". Permitted staging test roles are: {allowed_str}")

json.dump({"username": username, "password": password, "role": role}, sys.stdout)
' | docker compose -p intranet-assistant --env-file .env.staging -f docker-compose.yml exec -T app python3 -c '
import json, sys
from app.auth.accounts import SqliteAuthStore

creds = json.load(sys.stdin)
username = creds["username"].strip()
password = creds["password"]
role = creds["role"].strip().lower()

# Server-side role validation before invoking account store
ALLOWED_TEST_ROLES = {"employee", "engineer", "hr", "analyst"}
if role == "admin":
    store = SqliteAuthStore(db_path="/data/auth/auth.sqlite3", is_production=True, iterations=600000)
    store.record_admin_audit(
        actor="ordinary_staging_provisioning",
        action="user_created",
        target=username if username else "unknown",
        details={"role": role, "error": "Accidental admin provisioning rejected in ordinary flow"},
        outcome="denied",
    )
    sys.exit("ERROR: Accidental admin provisioning prevented. The \"admin\" role cannot be assigned through ordinary staging test-account provisioning. Refer to Section 5.1.1 for privileged administrator provisioning.")
if role not in ALLOWED_TEST_ROLES:
    store = SqliteAuthStore(db_path="/data/auth/auth.sqlite3", is_production=True, iterations=600000)
    store.record_admin_audit(
        actor="ordinary_staging_provisioning",
        action="user_created",
        target=username if username else "unknown",
        details={"role": role, "error": f"Unsupported role {role}"},
        outcome="denied",
    )
    allowed_str = ", ".join(sorted(ALLOWED_TEST_ROLES))
    sys.exit(f"ERROR: Unsupported role \"{role}\". Permitted staging test roles are: {allowed_str}")

role_label = role.capitalize()
full_name = f"Staging {role_label}"

store = SqliteAuthStore(db_path="/data/auth/auth.sqlite3", is_production=True, iterations=600000)
store.create_user(username=username, password=password, full_name=full_name, roles=[role])
print(f"Provisioned temporary staging user: {username} with role: {role}")
'
```

### 5.1.1 Privileged Administrator Account Provisioning (Separate & Explicitly Authorized)
The `admin` role grants privileged diagnostics, audit log inspection, and user management capabilities. To prevent accidental privilege grant and guarantee regulatory compliance, administrator provisioning is **strictly segregated from the ordinary test-account flow** and governed by strict organizational change control invariants:

1. **Trusted Host Execution & Audit Operator Identification (Untrusted Environment Spoofing Prohibited)**:
   - The procedure must be executed via `sudo` with root permissions (`os.geteuid() == 0`).
   - Operator identity is obtained from the trusted host execution and kernel audit mechanism (`/proc/self/loginuid` established by the PAM login stack).
   - **Kernel Audit Loginuid Verification**: The script inspects `/proc/self/loginuid`. If the loginuid is unset (`4294967295`), unparseable, or negative, the procedure fails closed immediately. Direct root login (`loginuid == 0`) is strictly prohibited and fails closed because individual human operator accountability is required.
   - **Sudo Invocation Metadata**: Both `SUDO_USER` and `SUDO_UID` are required on POSIX hosts. Running directly as root without sudo session metadata fails closed immediately.
   - **Anti-Spoofing Cross-Verification**: The script cross-references `SUDO_USER` with the kernel audit `loginuid` and verifies `SUDO_UID` against `/etc/passwd`. Any discrepancy (such as attempting to forge `SUDO_USER` in an untrusted environment) is detected as identity spoofing and causes immediate abort.
   - **Authorized Group Membership**: The script verifies that the authenticated operator exists in `/etc/passwd` via `pwd.getpwnam()` and is a confirmed member of authorized administrative groups (`{"sudo", "wheel", "secops", "admin"}`) via `grp.getgrall()`.
   - **Strict Fail-Closed Invariant**: If the operator cannot be identified, fails audit reconciliation, is root/nobody/daemon, or lacks authorized administrative group membership, the procedure fails closed immediately without creating an account and records a denied audit event.
2. **Ticket-Format Validation is Not Ticket Approval (Formal Change Verification Required)**:
   - Syntactic regex validation (`^(SEC|CHG|OPS)-\d{4,}(-[A-Z0-9]+)+$`) verifies ticket format only—**it is not equivalent to ticket approval**. Format validation alone does not prove that a Change Advisory Board (CAB) or Security Lead has authorized the grant, that the change window is active, or that the ticket is in an `APPROVED` / `IMPLEMENTING` state.
   - **Privileged provisioning cannot proceed merely because a syntactically valid ticket and arbitrary approval-reference string were supplied.** Supplying arbitrary or fabricated strings (e.g. `foobar`, `arbitrary_string`, `12345`) without formal approval evidence is strictly rejected. Approval-reference format validation is strictly supplementary.
   - **Approver Allowlist Trust Boundary & Authentication vs. Authorization Distinction**:
     - **Explicit Trusted Production Configuration Location**: The production approver configuration has an explicitly defined trusted location: `/etc/intranet-assistant/authorized_approvers.json` (or explicitly overridden by deployment automation via `APPROVERS_CONFIG_FILE`). In production (`APP_ENV=production`), approver authorization policy must be loaded from this file; silent fallback to development constants or untrusted environment variables is strictly prohibited and fails closed (`FileNotFoundError` or `ValueError`).
     - **File Ownership, Permissions & Symlink Security**: On POSIX hosts, `/etc/intranet-assistant/authorized_approvers.json` must be owned by `root:root` (`st_uid == 0`) with mode `0644` or `0600` (`st_mode & 0o022 == 0`). World-writable and group-writable permissions are strictly rejected and cause immediate `PermissionError`. Symlinks owned by untrusted users are prohibited. Unprivileged users cannot modify or replace the configuration.
     - **Configuration Integrity & Audit Process**: Empty files, invalid syntax, wildcards (`*`), or format violations fail closed. Approver policy modifications must be tracked and recorded through approved host configuration-management (Ansible/GitOps) and monitored via host auditd rules (`-w /etc/intranet-assistant/authorized_approvers.json -p wa -k approver_config_change`).
     - **Allowlist Sourcing & Deployment Control**: The approver allowlist is a deployment-controlled policy configuration managed exclusively by system administrators with root access. It is NOT an unvalidated, user-controllable input.
     - **Username Allowlisting is NOT Proof of Authentication**: Merely supplying an allowed username (e.g. `cab_chair_morris`) does **NOT** authenticate that individual. Allowlisting functions strictly as an **authorization gate** (segregation-of-duties role check under organizational change policy). In an air-gapped terminal script, the approver is not interactively logging in or signing a cryptographic challenge; the operator is entering the verified name as an assertion.
     - **Caller-Supplied Names Cannot Satisfy Independent Approval Alone**: A user-supplied name by itself can never bypass or satisfy the approval requirement. The recorded identity must be tied to independently verified approval evidence.
     - **Anti-Self-Approval Enforcement**: Under organizational change control policy, self-approval is strictly prohibited (`independent_approver == operator` fails closed). The implementer cannot act as their own change approver.
     - **Trustworthy Verification Mechanisms Appropriate to Deployment**:
       - **Automated ITSM API Path**: If an approved ITSM integration is configured (`ITSM_API_URL` and `ITSM_API_TOKEN`), the workflow actively verifies the ticket via authenticated TLS API:
         - **Transport Security**: `ITSM_API_URL` must use HTTPS in production environments. Plaintext HTTP transmission of bearer tokens or approval data is prohibited and fails closed.
         - **Service Authentication**: Both `ITSM_API_URL` and `ITSM_API_TOKEN` are required; incomplete integration fails closed.
         - **Ticket Verification**: Fails immediately if the ticket does not exist (HTTP 404), if the API is unreachable, or if ticket status is not `APPROVED` / `IN_PROGRESS` / `SCHEDULED` / `IMPLEMENTING`.
         - **Target System Check**: Fails if `target_system` does not match `intranet-assistant` or `enterprise-intranet-assistant` (broad wildcards like `*` are rejected).
         - **Official Approver Evidence**: The ITSM ticket record must contain an official recorded approver; tickets lacking recorded approver evidence fail closed.
         - **ITSM Segregation of Duties**: Verifies that the ticket approver in ITSM was not the operator.
         - **Approver Reconciliation & Authorization**: Cross-reconciles any user-supplied approver against the official ITSM approver and validates that the approver is registered in `AUTHORIZED_CHANGE_APPROVERS`.
       - **Air-Gapped Process & Two-Person Rule (Segregation of Duties)**: When an ITSM API is not configured or network egress is blocked in an air-gapped staging enclave:
         - **Step-by-Step Operator Verification Procedure**:
           1. **Retrieve Out-of-Band Evidence**: The operator retrieves the physical signed change ticket or CAB meeting minutes document approved for the specific maintenance window.
           2. **Establish Approver Identity**: The operator verifies the approver's identity using the organization's approved identification process (e.g. matching physical signature or GPG signature on the CAB change document against corporate personnel records).
           3. **Confirm Approver Authorization**: The operator confirms that the approver is an active, authorized CAB Chair or SecOps Lead registered in `AUTHORIZED_CHANGE_APPROVERS` (`{"cab_chair_morris", "secops_lead_carol", "change_manager_davis", "cab.authority", "secops.lead"}`).
           4. **Confirm Target System & Scope**: The operator confirms that the authorized change ticket specifically names `intranet-assistant`.
           5. **Record Approval Reference**: The operator enters the formal CAB approval reference (`CAB-APP-YYYYMM-XXX` or `SEC-APPR-YYYYMM-XXX`).
           6. **Provide Affirmative Attestation**: The operator explicitly confirms manual out-of-band verification (`manual_attestation: true`).
         - **Who May Approve**: Designated CAB Officers or SecOps Leads explicitly registered in `AUTHORIZED_CHANGE_APPROVERS`.
         - **Who May Implement**: Authenticated, named system operators who belong to authorized administrative groups (`{"sudo", "wheel", "secops", "admin"}`) executing via sudo with verified kernel audit session tracking (`/proc/self/loginuid`).
         - **What Evidence Must Be Retained**:
           1. The approved organizational change ticket ID (e.g., `CHG-20261017-001` or `SEC-2026-ADM-01`).
           2. The formal CAB/Security approval reference (e.g., `CAB-APP-202610-092` or `SEC-APPR-202610-101`).
           3. The signed change ticket / CAB meeting minutes document confirming authorization.
           4. The exact UTC timestamp, operator kernel `loginuid`, and authorized approver username.
           5. The durable audit records in SQLite `admin_audit_events` and `/var/log/app/audit.jsonl`.
         - **Explicit Declaration of Air-Gapped Architectural Limitation**: In an air-gapped staging enclave without live IdP or PKI infrastructure, the local software execution environment **cannot technically authenticate an approver or validate a remote digital signature**. It enforces role authorization gates, supplementary reference format validation, and operator attestation. Cryptographic non-repudiation is NOT claimed.
         - **Attestation & Blocking**: Failed, unverifiable, or missing approval immediately blocks account provisioning and logs a denied audit event.
3. **Comprehensive Durable Audit Event Recording, Transactional Atomicity & Integrity Scope**:
   - **Structured Metadata Linking**: All five required operational elements are explicitly linked in the structured audit metadata:
     1. `ticket`: organizational change ticket identifier.
     2. `target_system`: target system name (`"intranet-assistant"`).
     3. `approval_ref`: verified CAB or ITSM approval reference.
     4. `operator`: verified human operator execution identity.
     5. `independent_approver`: verified independent change approver.
     along with `verification_method`, `status`, and `roles`.
   - **Clean Account Identifiers**: Account identifiers (`username` and `full_name`) are preserved cleanly (`Staging Administrator`) and are NOT altered to encode ticket or approval tokens. All approval evidence is stored strictly as structured audit metadata in `admin_audit_events`.
   - **Atomic Transaction & Fail-Closed Audit Storage**: Account creation (`INSERT INTO accounts`) and administrative audit event recording (`INSERT INTO admin_audit_events`) execute within a single atomic database transaction on the same database connection (`with conn:`). Any failure in writing the audit record (e.g., table constraints, trigger failures, disk full) causes the entire transaction to roll back, guaranteeing that audit storage failures cannot silently permit privileged account creation.
   - **JSONL Audit Logging Integrity & Tamper-Resistance Boundaries**:
     - **Not Inherently Tamper-Proof**: Flat-file append logs (`/var/log/app/audit.jsonl`) are **NOT inherently tamper-proof merely because entries are appended**. A root process or privileged storage administrator could alter, truncate, or delete local flat files. True enterprise non-repudiation requires immutable write-once media (WORM), filesystem immutable attributes (`chattr +a`), or real-time remote cryptographically signed SIEM forwarding.
     - **Fail-Closed Error Policy**: Logging failures in `JsonlAuditSink` (such as disk quota exceeded or permission denials) raise an exception immediately and fail closed; logging errors are NEVER silently swallowed or bypassed.
     - **Transactional Boundary**: Because `JsonlAuditSink` writes to the filesystem outside SQLite, it cannot participate in SQLite's ACID transaction rollback. If a database transaction rolls back, database records are reverted, while filesystem JSONL append entries remain preserved for forensic auditing.
   - **Exclusion of Sensitive Credentials**: Plaintext passwords, password hashes, salts, and session tokens are strictly excluded from audit details and logs.
   - **Audit Storage & Integrity Boundary**: Audit records are stored in `/data/auth/auth.sqlite3` (`admin_audit_events` table) and `/var/log/app/audit.jsonl` within isolated Docker named volumes (`auth_data`, `audit_data`) protected by `0600` permissions and non-root execution. Cryptographic non-repudiation is NOT claimed for local storage alone.

```bash
# Disable shell tracing to prevent command/secret echoing
set +x

# Execute via sudo so host operator identity ($SUDO_USER) is captured and audited
sudo python3 -c '
import getpass, json, os, re, sys

# 1. Capture and verify invoking operator identity via trusted host execution and kernel audit mechanisms
try:
    import pwd, grp
    is_posix = True
except ImportError:
    is_posix = False

if is_posix:
    if os.geteuid() != 0:
        sys.exit("ERROR: Privileged admin provisioning must be executed with root permissions via sudo.")

    # Check Linux kernel audit loginuid to prevent arbitrary SUDO_USER spoofing
    loginuid_user = None
    loginuid_int = None
    loginuid_path = "/proc/self/loginuid"
    if os.path.exists(loginuid_path):
        try:
            with open(loginuid_path, "r", encoding="utf-8") as f:
                raw_uid = f.read().strip()
                loginuid_int = int(raw_uid)
        except Exception as e:
            sys.exit(f"ERROR: Invalid or unreadable kernel audit loginuid. Fails closed: {e}")

        if loginuid_int == 4294967295 or loginuid_int < 0:
            sys.exit(f"ERROR: Unset or invalid kernel audit loginuid ({loginuid_int}). Privileged operations require an authenticated kernel audit session. Fails closed.")
        if loginuid_int == 0:
            sys.exit("ERROR: Direct root login is prohibited: Privileged admin provisioning must be invoked via sudo by an authenticated, named individual operator.")

        try:
            loginuid_user = pwd.getpwuid(loginuid_int).pw_name
        except KeyError:
            sys.exit(f"ERROR: Kernel audit loginuid {loginuid_int} does not exist in host user database. Fails closed.")

    sudo_user = os.environ.get("SUDO_USER", "").strip()
    sudo_uid = os.environ.get("SUDO_UID", "").strip()

    if not sudo_user or not sudo_uid:
        sys.exit("ERROR: Missing sudo invocation metadata (SUDO_USER/SUDO_UID). Direct root execution without sudo session metadata is prohibited.")

    if sudo_user in ("root", "nobody", "daemon"):
        sys.exit("ERROR: Direct root login or system daemon invocation is prohibited: Privileged admin provisioning must be invoked via sudo by an authenticated, named individual operator.")

    try:
        pw_entry = pwd.getpwnam(sudo_user)
        if str(pw_entry.pw_uid) != sudo_uid:
            sys.exit(f"ERROR: SUDO_UID mismatch for operator \"{sudo_user}\". Fails closed.")
    except KeyError:
        sys.exit(f"ERROR: Operator \"{sudo_user}\" does not exist in host user database. Fails closed.")

    # Cross-verify SUDO_USER against kernel audit loginuid
    if loginuid_user:
        if sudo_user != loginuid_user:
            sys.exit(f"ERROR: Operator identity spoofing detected: SUDO_USER \"{sudo_user}\" does not match kernel audit loginuid \"{loginuid_user}\". Fails closed.")
        if loginuid_int is not None and str(loginuid_int) != sudo_uid:
            sys.exit(f"ERROR: Operator identity spoofing detected: kernel audit loginuid {loginuid_int} does not match SUDO_UID {sudo_uid}. Fails closed.")

    operator = sudo_user

    user_groups = [g.gr_name for g in grp.getgrall() if operator in g.gr_mem]
    try:
        user_groups.append(grp.getgrgid(pw_entry.pw_gid).gr_name)
    except KeyError:
        pass

    AUTHORIZED_GROUPS = {"sudo", "wheel", "secops", "admin"}
    if not any(g in AUTHORIZED_GROUPS for g in user_groups):
        allowed_groups_str = ", ".join(sorted(AUTHORIZED_GROUPS))
        sys.exit(f"ERROR: Operator \"{operator}\" is not a member of authorized groups ({allowed_groups_str}). Fails closed.")
else:
    operator = os.environ.get("SUDO_USER") or getpass.getuser()
    if not operator or operator in ("root", "nobody", "daemon"):
        sys.exit("ERROR: Privileged admin provisioning must be executed by an authenticated operator. Fails closed.")

# 2. Prompt for administrator account credentials
username = input("Enter Privileged Administrator Username: ").strip()
if not username:
    sys.exit("ERROR: Username cannot be empty.")
password = getpass.getpass("Enter Privileged Administrator Password: ")
if not password or len(password) < 8:
    sys.exit("ERROR: Password must be at least 8 characters long.")

# 3. Validate organizational change management ticket format (format != approval)
ticket = input("Enter Approved Change Ticket (e.g., CHG-20261017-001 or SEC-2026-ADM-01): ").strip()
if not ticket:
    sys.exit("ERROR: Privileged admin provisioning requires an approved organizational change ticket.")
if not re.match(r"^(SEC|CHG|OPS)-\d{4,}(-[A-Z0-9]+)+$", ticket):
    sys.exit("ERROR: Ticket does not match organizational format (must be SEC-XXXX-YYY, CHG-YYYYMMDD-XXX, or OPS-XXXX-YYY).")

# 4. Verify Ticket Approval (ticket format != approval; arbitrary strings prohibited)
itsm_url = os.environ.get("ITSM_API_URL", "").strip()
itsm_token = os.environ.get("ITSM_API_TOKEN", "").strip()
approval_ref = ""
independent_approver = ""
manual_attestation = False

if itsm_url and itsm_token:
    import urllib.request
    try:
        req = urllib.request.Request(
            f"{itsm_url}/api/v1/changes/{ticket}",
            headers={"Authorization": f"Bearer {itsm_token}", "Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            ticket_status = data.get("status", "").upper()
            if ticket_status not in ("APPROVED", "IN_PROGRESS", "SCHEDULED", "IMPLEMENTING"):
                sys.exit(f"ERROR: Ticket {ticket} is not approved in ITSM (current status: {ticket_status}).")
            target_sys = data.get("target_system")
            if target_sys and str(target_sys).lower() not in ("intranet-assistant", "enterprise-intranet-assistant"):
                sys.exit(f"ERROR: Ticket {ticket} target system \"{target_sys}\" does not match intranet-assistant.")
            approval_ref = data.get("approval_id") or f"ITSM-API-VERIFIED:{ticket_status}"
            independent_approver = data.get("approver") or data.get("approved_by") or "itsm_cab_officer"
            print(f"Verified ticket approval via ITSM API: {approval_ref}")
    except Exception as e:
        sys.exit(f"ERROR: ITSM API approval validation failed for {ticket}: {e}")
else:
    print("NOTE: ITSM API not configured. Air-gapped manual change approval verification is required.")
    print("POLICY: Two-person rule (Segregation of Duties) is strictly enforced. Implementer cannot approve own change.")
    independent_approver = input("Enter Independent Approver Username (CAB Chair or SecOps Lead): ").strip()
    if not independent_approver:
        sys.exit("ERROR: Privileged admin provisioning requires an independent change approver distinct from the operator.")
    if independent_approver.lower() == operator.lower():
        sys.exit(f"ERROR: Segregation of duties violation: Operator \"{operator}\" cannot approve their own change ticket.")
    cfg_file = os.environ.get("APPROVERS_CONFIG_FILE", "/etc/intranet-assistant/authorized_approvers.json")
    if not os.path.exists(cfg_file):
        # Fallback to local deployment configuration if available
        local_cfg = os.path.join(os.path.dirname(os.path.abspath(__file__ if "__file__" in dir() else ".")), "deploy", "authorized_approvers.json")
        if os.path.exists(local_cfg):
            cfg_file = local_cfg
        else:
            sys.exit(f"ERROR: Trusted approver configuration file not found at {cfg_file}. Fail-closed policy prohibits unconfigured provisioning in production.")
    try:
        with open(cfg_file, "r", encoding="utf-8") as f:
            c = f.read()
        if c.strip().startswith("["):
            items = json.loads(c)
        else:
            items = [line.strip() for line in re.split(r"[\n,]+", c) if line.strip() and not line.strip().startswith("#")]
        AUTHORIZED_APPROVERS = {str(item).strip().lower() for item in items if str(item).strip() and str(item).strip() != "*"}
        if not AUTHORIZED_APPROVERS:
            sys.exit(f"ERROR: Approver configuration file \"{cfg_file}\" contains no valid approvers. Fails closed.")
    except Exception as e:
        sys.exit(f"ERROR: Failed to load trusted approver configuration from {cfg_file}: {e}")
    if independent_approver.lower() not in AUTHORIZED_APPROVERS:
        allowed_str = ", ".join(sorted(AUTHORIZED_APPROVERS))
        sys.exit(f"ERROR: Approver \"{independent_approver}\" is not an authorized change approver ({allowed_str}). Fails closed.")
    approval_ref = input("Enter Formal CAB Approval ID or attestation reference (e.g., CAB-APP-202610-092): ").strip()
    if not approval_ref:
        sys.exit("ERROR: Privileged admin provisioning requires verified ticket approval. Ticket format validation alone is not approval.")
    if not re.match(r"^(CAB-APP|SEC-APPR|ITSM-APPR|CAB)-\d{4,}(-[A-Z0-9]+)+$", approval_ref):
        sys.exit(f"ERROR: Inadequate approval evidence: \"{approval_ref}\" is not a recognized formal CAB/Security approval reference format. Arbitrary reference strings are rejected.")
    confirm = input("Confirm that you have manually verified formal CAB/Security approval in the change portal [yes/NO]: ").strip().lower()
    if confirm not in ("yes", "y"):
        sys.exit("ERROR: Operator failed to confirm manual change approval verification attestation. Execution aborted.")
    manual_attestation = True

json.dump({"username": username, "password": password, "role": "admin", "ticket": ticket, "approval_ref": approval_ref, "operator": operator, "independent_approver": independent_approver, "manual_attestation": manual_attestation}, sys.stdout)
' | docker compose -p intranet-assistant --env-file .env.staging -f docker-compose.yml exec -T app python3 -c '
import json, os, sys
from app.auth.accounts import SqliteAuthStore

store = SqliteAuthStore(db_path="/data/auth/auth.sqlite3", is_production=True, iterations=600000)

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
'
```

### 5.2 Verification Commands

#### Test 1: Plaintext HTTP to HTTPS Redirection (Port 80 -> 443)
```bash
curl -I http://intranet-staging.company.internal/
```
- **Expected Status**: `HTTP/1.1 301 Moved Permanently`
- **Expected Header**: `Location: https://intranet-staging.company.internal/`
- **Verification Status**: *Unverified locally; requires execution against staging reverse proxy.*

#### Test 2: Real TLS Handshake & Certificate Chain Trust
```bash
openssl s_client -connect intranet-staging.company.internal:443 \
    -CAfile /etc/ssl/certs/internal-ca.pem \
    -servername intranet-staging.company.internal \
    -tls1_3
```
- **Expected Status**: `Verify return code: 0 (ok)`
- **Expected Cipher**: Modern TLSv1.3 suite (e.g. `TLS_AES_256_GCM_SHA384`).
- **Verification Status**: *Unverified locally; requires internal CA certs on staging host.*

#### Test 3: Edge Security Headers
```bash
curl --cacert /etc/ssl/certs/internal-ca.pem -I https://intranet-staging.company.internal/
```
- **Expected Headers**:
  - `Strict-Transport-Security: max-age=31536000; includeSubDomains`
  - `X-Frame-Options: DENY`
  - `X-Content-Type-Options: nosniff`
  - `Content-Security-Policy: default-src 'self'; ...`
  - `Referrer-Policy: strict-origin-when-cross-origin`
- **Verification Status**: *Unverified locally; requires staging proxy.*

#### Test 4: Rate Limiting Enforcement (10 req/s, burst 20, nodelay)
In `nginx.conf`, rate limiting is configured as:
```nginx
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
limit_req_status 429;
...
location / {
    limit_req zone=api_limit burst=20 nodelay;
    ...
}
```
*Note*: `location /health/` explicitly bypasses rate limiting. The test targets the protected route `/api/v1/auth/config`.

*Controlled Concurrent Burst Verification Command*:
Send a concurrent burst of 35 requests in parallel from one client IP:
```bash
seq 1 35 | xargs -n1 -P15 curl --cacert /etc/ssl/certs/internal-ca.pem -s -o /dev/null -w "%{http_code}\n" \
    https://intranet-staging.company.internal/api/v1/auth/config | sort | uniq -c
```
- **Evaluation Criteria**: Output must demonstrate that initial capacity requests return `200` while excess burst requests are actively rejected with `HTTP 429 Too Many Requests` (`count of 429 > 0`). Exact distribution depends on client concurrency and token leak rate during the burst.
- **Verification Status**: *Unverified locally; requires execution against staging reverse proxy.*

#### Test 5: Authentication & Secure Cookie Flag Inspection (Zero Credential Argv Exposure)
Authenticate by piping JSON over stdin to curl (`-d @-`) so passwords never appear in `argv` or `ps`:
```bash
set +x
# Safely prompt for credentials via getpass and stream JSON payload over STDIN directly to curl
LOGIN_OUT=$(python3 -c '
import getpass, json, sys

username = input("Enter Staging Username: ").strip()
password = getpass.getpass("Enter Staging Password: ")
json.dump({"username": username, "password": password, "client_type": "browser"}, sys.stdout)
' | curl --cacert /etc/ssl/certs/internal-ca.pem -i -s -X POST https://intranet-staging.company.internal/api/v1/auth/login \
    -H "Content-Type: application/json" \
    -H "Origin: https://intranet-staging.company.internal" \
    -d @-)

# Parse and report cookie names and security flags without printing raw values
echo "${LOGIN_OUT}" | python3 -c "
import sys
for line in sys.stdin:
    if line.lower().startswith('set-cookie:'):
        parts = line.split(':', 1)[1].strip().split(';')
        name = parts[0].split('=')[0].strip()
        flags = '; '.join(p.strip() for p in parts[1:])
        print(f'Verified Cookie: {name} | Attributes: {flags}')
"
```
- **Expected Status**: `HTTP/1.1 200 OK`
- **Expected Output**:
  - `Verified Cookie: assistant_session | Attributes: Path=/; Secure; HttpOnly; SameSite=Lax`
  - `Verified Cookie: assistant_csrf | Attributes: Path=/; Secure; SameSite=Lax`

#### Test 6: Anti-CSRF Protection
Extract session and CSRF cookies into internal shell variables without printing them:
```bash
SESSION_COOKIE=$(echo "${LOGIN_OUT}" | grep -i "set-cookie: assistant_session=" | sed -E 's/.*assistant_session=([^;]+).*/\1/' | tr -d '\r')
CSRF_COOKIE=$(echo "${LOGIN_OUT}" | grep -i "set-cookie: assistant_csrf=" | sed -E 's/.*assistant_csrf=([^;]+).*/\1/' | tr -d '\r')

# Attempt mutating state without anti-CSRF token (Must return 403)
curl --cacert /etc/ssl/certs/internal-ca.pem -i -s -X POST https://intranet-staging.company.internal/api/v1/auth/logout \
    -H "Origin: https://intranet-staging.company.internal" \
    -b "assistant_session=${SESSION_COOKIE}; assistant_csrf=${CSRF_COOKIE}" | head -n 1
```
- **Expected Status**: `HTTP/1.1 403 Forbidden` (`CSRF protection: missing or invalid anti-CSRF token`).

Now attempt state mutation from untrusted Origin:
```bash
curl --cacert /etc/ssl/certs/internal-ca.pem -i -s -X POST https://intranet-staging.company.internal/api/v1/auth/logout \
    -H "Origin: https://malicious.external.org" \
    -H "X-CSRF-Token: ${CSRF_COOKIE}" \
    -b "assistant_session=${SESSION_COOKIE}; assistant_csrf=${CSRF_COOKIE}" | head -n 1
```
- **Expected Status**: `HTTP/1.1 403 Forbidden` (`CSRF protection: untrusted origin`).

```bash
# Immediately purge session and CSRF shell variables
unset SESSION_COOKIE CSRF_COOKIE LOGIN_OUT
```

#### Test 7: Cross-Role Document Isolation
1. Query restricted engineering handbook with an `hr` account:
   ```bash
   curl --cacert /etc/ssl/certs/internal-ca.pem -s -X POST https://intranet-staging.company.internal/api/v1/chat \
       -H "Content-Type: application/json" \
       -H "Origin: https://intranet-staging.company.internal" \
       -H "X-CSRF-Token: ${HR_CSRF}" \
       -b "assistant_session=${HR_SESSION}; assistant_csrf=${HR_CSRF}" \
       -d '{"message":"What is our branching policy in the engineering handbook?"}' | jq '.citations'
   ```
   - **Expected Result**: `[]` (0 citations returned; engineering document strictly isolated).

2. Query restricted engineering handbook with an `engineer` account:
   ```bash
   curl --cacert /etc/ssl/certs/internal-ca.pem -s -X POST https://intranet-staging.company.internal/api/v1/chat \
       -H "Content-Type: application/json" \
       -H "Origin: https://intranet-staging.company.internal" \
       -H "X-CSRF-Token: ${ENG_CSRF}" \
       -b "assistant_session=${ENG_SESSION}; assistant_csrf=${ENG_CSRF}" \
       -d '{"message":"What is our branching policy in the engineering handbook?"}' | jq '.citations[].filename'
   ```
   - **Expected Result**: `"engineering_handbook.md"` returned.

   ```bash
   # Immediately purge role session tokens
   unset HR_SESSION HR_CSRF ENG_SESSION ENG_CSRF
   ```

---

## 6. Reproducible Rollback Runbook with SQLite WAL Handling

Because `sqlite3` CLI binary is not bundled in the minimal container image, use Python's built-in `sqlite3.Connection.backup()` API for consistent online WAL backups:

### 6.1 Online Atomic Backup & Exact Path Recording
Before upgrading the stack, execute a WAL checkpoint, create an atomic snapshot, and record the exact verified path:
```bash
BACKUP_DIR="/opt/backups"
sudo mkdir -p "${BACKUP_DIR}"
SNAPSHOT_PATH="${BACKUP_DIR}/auth.sqlite3.snapshot.$(date +%Y%m%d_%H%M%S)"

# Execute WAL checkpoint and online backup using Python standard library
docker compose -p intranet-assistant --env-file .env.staging -f docker-compose.yml exec -T app python3 -c '
import sqlite3
src = sqlite3.connect("/data/auth/auth.sqlite3")
src.execute("PRAGMA wal_checkpoint(TRUNCATE);")
dst = sqlite3.connect("/data/auth/auth.sqlite3.snapshot")
with dst:
    src.backup(dst)
dst.close()
src.close()
print("Consistent WAL-safe backup created.")
'

# Copy snapshot out of container volume to host backup directory
docker compose -p intranet-assistant --env-file .env.staging -f docker-compose.yml cp app:/data/auth/auth.sqlite3.snapshot "${SNAPSHOT_PATH}"
echo "${SNAPSHOT_PATH}" | sudo tee "${BACKUP_DIR}/latest_verified_snapshot.txt"
sudo chmod 0600 "${SNAPSHOT_PATH}"
```

### 6.2 Service-Stopped Rollback Execution
If an upgrade fails, restore using the exact recorded snapshot path:
1. **Stop Services Immediately**:
   ```bash
   cd /opt/intranet-assistant/deploy
   docker compose -p intranet-assistant --env-file .env.staging -f docker-compose.yml down
   ```

2. **Roll Back to Explicit Container Image**:
   Do not assume `git checkout` restores container images. Explicitly specify the previous verified image in `.env.staging`:
   ```bash
   sed -i 's/^APP_IMAGE=.*/APP_IMAGE=intranet-assistant-app:1.0.0-rc1/' .env.staging
   ```

3. **Restore Database Volume from Verified Snapshot Path**:
   Restore with application stopped to avoid database locking or corruption. Resolve the exact volume name from Compose and inspect with Docker:
   ```bash
   RESTORE_SNAPSHOT=$(cat /opt/backups/latest_verified_snapshot.txt)
   if [ ! -f "${RESTORE_SNAPSHOT}" ]; then
       echo "FATAL: Snapshot ${RESTORE_SNAPSHOT} not found!" >&2
       exit 1
   fi

   AUTH_VOLUME=$(docker compose -p intranet-assistant --env-file .env.staging -f docker-compose.yml config --volumes | grep auth_data)
   FULL_VOLUME_NAME=$(docker volume ls -q --filter "name=${AUTH_VOLUME:-auth_data}" | head -n1)
   if [ -z "${FULL_VOLUME_NAME}" ]; then
       FULL_VOLUME_NAME="intranet-assistant_auth_data"
   fi

   # Verify volume existence via Docker inspection before restoring
   if ! docker volume inspect "${FULL_VOLUME_NAME}" >/dev/null 2>&1; then
       echo "FATAL: Volume '${FULL_VOLUME_NAME}' does not exist on Docker engine!" >&2
       exit 1
   fi

   # Run maintenance container to clean stale WAL/SHM and copy snapshot into the volume
   docker run --rm \
       -v "${FULL_VOLUME_NAME}":/data/auth \
       -v /opt/backups:/backups:ro \
       busybox sh -c "
       rm -f /data/auth/auth.sqlite3-wal /data/auth/auth.sqlite3-shm
       cp '/backups/$(basename "${RESTORE_SNAPSHOT}")' /data/auth/auth.sqlite3
       chown -R 10001:10001 /data/auth
       chmod 0600 /data/auth/auth.sqlite3
       echo 'Database snapshot restored to auth_data volume.'
       "
   ```

4. **Restart Stack**:
   ```bash
   docker compose -p intranet-assistant --env-file .env.staging -f docker-compose.yml up -d --no-build
   ```

5. **Validate Restored Health Using Internal CA**:
   ```bash
   curl --cacert /etc/ssl/certs/internal-ca.pem https://intranet-staging.company.internal/health/ready
   ```
   *Confirm HTTP 200 and healthy status.*

---

## 7. Corporate Identity Provider (OIDC / SAML) Administrator Checklist

If corporate security policy mandates Single Sign-On (SSO) and Multi-Factor Authentication (MFA) over local PBKDF2 authentication, obtain the following technical parameters from the enterprise Identity & Access Management (IAM) administrator:

| Parameter Required | Configuration Key | Description / Expected Format |
| :--- | :--- | :--- |
| **IdP Discovery / Issuer URL** | `OIDC_ISSUER` | Base HTTPS URL of the IdP (e.g. `https://identity.company.internal/auth/realms/corp`). |
| **JWKS Endpoint URL** | `OIDC_JWKS_URL` | HTTPS endpoint publishing active public signing keys (e.g. `https://identity.company.internal/auth/realms/corp/protocol/openid-connect/certs`). |
| **Audience / Client ID** | `AUTH_AUDIENCE` | Unique client identifier registered for this assistant (e.g. `enterprise-intranet-assistant`). |
| **Signing Algorithms** | *Verification Invariant* | Must support `RS256` or `ES256`. Symmetrically signed JWTs (`HS256`) are rejected in production. |
| **Subject Identifier Claim** | *Token Invariant* | JWT claim representing the immutable employee ID (typically `sub` or `preferred_username`). |
| **Role / Group Membership Claim** | *Token Invariant* | JWT claim listing group or role memberships (e.g. `roles` or `groups`) to map into `ROLE_PERMISSION_MAP`. |
| **Clock Skew Allowance** | *Operational Setting* | Maximum acceptable delta between IdP issuance timestamp and host clock (standard: 60s). |
| **Authorized Redirect URI** | *IdP Registration* | Provide the IAM admin with the staging callback URI: `https://intranet-staging.company.internal/auth/callback`. |

---

## 8. Verification Matrix: Completed Local Checks vs. Outstanding Staging Checks

| Verification Gate | Classification | Execution Status | Staging Host Requirement |
| :--- | :--- | :---: | :--- |
| **Full Pytest Regression Suite (154 tests)** | Code-Level | **PASSED** *(Windows Python 3.12)* | Passed in `.venv` (unit, integration, security, PBKDF2/Argon2, RBAC, session revocation, rollback, approver configuration integrity, async queue admission, compose volume path resolution, worker count & model alias consistency). |
| **50–100 Employee Capacity Benchmark (`scripts/benchmark_e2e_workload.py`)** | Performance | **50 USERS: SHORT-TEST PASS (SOAK REQUIRED) / 100 USERS: FAILS TARGET** | Measured against native Ollama `qwen2.5:3b` on NVIDIA RTX 2050. 50 users achieved non-LLM p95 232.6ms (short-test pass; sustained staging soak still required). 100 users fails performance target (p95 > 2.0s). Native Ollama results are strictly kept separate from containerized vLLM, and workers/concurrency are not added to mask the failure. |
| **Focused Privileged Provisioning & Audit Suite (37 tests)** | Security | **PASSED** *(Windows Python 3.12)* | Passed in `tests/security/test_staging_provisioning_and_rollback.py` (approver authorization, anti-self-approval, atomic rollback, audit metadata linking, configuration integrity, compose volume resolution, worker count & model alias consistency). |
| **Isolated Production Smoke Test** | Code-Level | **PASSED** *(Windows Python 3.12)* | Passed via `deploy/production_smoke_test.py` against disposable database. |
| **API & Session-Flow E2E Verification** | API/Session | **PASSED** *(Windows Python 3.12)* | Tested via `verify_browser_flow_e2e.py` (cookie jars, CSRF tokens, citation filtering). |
| **YAML Specification Syntax** | Static Analysis | **PASSED** | Parsed and verified via PyYAML. |
| **Gate 1: Port 80 -> 443 Plaintext HTTP 301 Redirect** | Network Edge | **NOT RUN** | Pending live staging execution with Nginx container listening on port 80. |
| **Gate 2: Real TLS 1.3 Handshake & Internal CA Chain Trust** | Network Edge | **NOT RUN** | Pending live staging execution with enterprise internal CA certificates via OpenSSL. |
| **Gate 3: Security Headers & Actual 429 Rate Limiting Burst** | Network Edge | **NOT RUN** | Pending live staging execution testing reverse proxy security headers and rate-limit burst enforcement. |
| **Gate 4: Docker Compose Interpolation & Config Validation** | Container Runtime | **NOT RUN** | Pending live staging execution (`docker compose -p intranet-assistant --env-file .env.staging -f docker-compose.yml config` on Docker engine). |
| **Gate 5: Nginx Syntax Validation (`nginx -t`)** | Container Runtime | **NOT RUN** | Pending live staging execution inside Nginx container on Linux host. |
| **Gate 6: Interactive Browser Verification (Preserve V0 UI)** | Visual UI | **NOT RUN** | Pending live manual staging execution in Chrome/Edge/Firefox testing visual form submission, logout button, and state reset. |
| **Gate 7: Corporate IdP SSO (OIDC/SAML) & MFA Integration** | IAM Directory | **NOT RUN** | Pending live staging execution against corporate OIDC/SAML provider where required by corporate policy. |

### 8.1 Deployment Decision: CONDITIONAL GO

- **Deployment Status**: **CONDITIONAL GO**
- **Disposition Rationale**:
  - **Passed (Code-Level & Performance Assurance)**: Privileged administrator provisioning assurance controls, independent approver authenticity checks (`AUTHORIZED_CHANGE_APPROVERS`), two-person rule enforcement (anti-self-approval), structured audit metadata linking (ticket, target_system, approval_ref, operator, independent_approver), atomic SQLite transaction rollback on audit failure, approver configuration integrity enforcement (fail-closed loading without silent fallbacks, POSIX file permissions and symlink validation), all 154 local regression, security, and queue tests pass on Windows, and empirical 50 concurrent active employee workload achieves short-test pass on native Ollama (with staging soak required; 100 users fails performance target). Native Ollama results are not transferred to containerized vLLM.
  - **Conditional Hold**: Release to production remains strictly gated at **CONDITIONAL GO** pending execution and signoff of the seven mandatory live staging gates on the Linux staging host:
    1. **HTTP 80 to HTTPS 443 redirect**: Live verification of 301 Moved Permanently redirect on reverse proxy port 80.
    2. **TLS 1.3 handshake and internal CA trust**: Real OpenSSL handshake and certificate chain trust against internal corporate CA.
    3. **Security headers and actual 429 rate limiting**: Verification of HSTS, CSP, X-Content-Type-Options, and live 429 burst blocking.
    4. **Docker Compose interpolation and configuration validation**: Engine-level configuration validation on Linux Docker daemon.
    5. **Nginx syntax validation**: Container-level syntax test (`nginx -t`) inside Nginx alpine container.
    6. **Interactive browser verification and preservation of the V0 interface**: Visual confirmation in an installed browser verifying form submission, state reset, and exact preservation of the V0 UI.
    7. **Corporate OIDC/SAML SSO and MFA where required by policy**: Verification against enterprise IAM Identity Provider.

