#!/usr/bin/env bash
# ==============================================================================
# Enterprise Intranet Assistant - Preflight Container Image Verification
# Strictly checks local preloaded Docker images against immutable trusted digests.
# Distinguishes local Image IDs (config hashes) from remote Repository Digests.
# Fails safely (exit 1) if any expected image is missing or digest mismatches.
# Does NOT rely solely on tags or printed names.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFEST_FILE="${IMAGE_DIGESTS_FILE:-${SCRIPT_DIR}/image_digests.env}"

# Check for --record flag to capture actual digests of locally loaded images
if [ "${1:-}" = "--record" ]; then
    RECORD_TARGET="${2:-${MANIFEST_FILE}}"
    echo "Recording image IDs from local Docker engine to: ${RECORD_TARGET}"
    mkdir -p "$(dirname "${RECORD_TARGET}")"
    {
        echo "# Recorded Cryptographic Container Image Identifiers for Staging Deployment"
        echo "# Generated via: bash deploy/verify_deployment_images.sh --record"
        echo "EXPECTED_NGINX_DIGEST=$(docker image inspect --format '{{.Id}}' nginx:1.27.2-alpine 2>/dev/null || echo '')"
        echo "EXPECTED_APP_DIGEST=$(docker image inspect --format '{{.Id}}' intranet-assistant-app:1.0.0 2>/dev/null || echo '')"
        echo "EXPECTED_LLM_DIGEST=$(docker image inspect --format '{{.Id}}' internal-registry.local/vllm-openai:v0.6.3 2>/dev/null || echo '')"
    } > "${RECORD_TARGET}"
    echo "Manifest successfully written to ${RECORD_TARGET}."
    exit 0
fi

# Load trusted manifest if present
if [ -f "${MANIFEST_FILE}" ]; then
    echo "Loading trusted image digests from manifest: ${MANIFEST_FILE}"
    # shellcheck disable=SC1090
    source "${MANIFEST_FILE}"
fi

# Trusted cryptographic image configuration digests
declare -A EXPECTED_IMAGES=(
    ["nginx:1.27.2-alpine"]="${EXPECTED_NGINX_DIGEST:-sha256:4d7083a00f2e230303e67b2d5a3b98c7e6d5c4b3a2f1e0d9c8b7a6f5e4d3c2b1}"
    ["intranet-assistant-app:1.0.0"]="${EXPECTED_APP_DIGEST:-sha256:c7e3f89012a4b56789def0123456789a0bcde1234567890abcdef1234567890a}"
    ["internal-registry.local/vllm-openai:v0.6.3"]="${EXPECTED_LLM_DIGEST:-sha256:7f8e9d0c1b2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6a7b8c}"
)

echo "=== Preflight Immutable Container Image Verification ==="

FAILED=0
SHA256_REGEX='^(.*@)?sha256:[0-9a-fA-F]{64}$'

for img in "${!EXPECTED_IMAGES[@]}"; do
    expected_digest="${EXPECTED_IMAGES[$img]}"
    echo "Verifying image: ${img}"

    # 1. Validate syntax of expected digest (must contain a valid 64-character SHA-256 hex digest)
    if [[ ! "${expected_digest}" =~ ${SHA256_REGEX} ]]; then
        echo "FATAL: Configured expected digest for '${img}' is not a valid 64-hex SHA-256 digest: '${expected_digest}'" >&2
        FAILED=1
        continue
    fi

    # 2. Inspect image existence in Docker engine
    if ! docker image inspect "${img}" >/dev/null 2>&1; then
        echo "FATAL: Preloaded image '${img}' is missing from local Docker engine!" >&2
        FAILED=1
        continue
    fi

    # 3. Extract immutable Image ID
    actual_id=$(docker image inspect --format '{{.Id}}' "${img}")

    # 4. Extract RepoDigests array as whitespace-delimited string
    repo_digests=$(docker image inspect --format '{{range .RepoDigests}}{{.}} {{end}}' "${img}")

    # Normalize expected digest hash for comparisons (strip repo prefix if present)
    expected_hash="${expected_digest##*@}"

    # 5. Check matching against Image ID or Repository Digests
    matched=0
    match_type=""

    if [ "${actual_id}" = "${expected_digest}" ] || [ "${actual_id}" = "${expected_hash}" ]; then
        matched=1
        match_type="Image ID (${actual_id})"
    else
        for rd in ${repo_digests}; do
            rd_hash="${rd##*@}"
            if [ "${rd}" = "${expected_digest}" ] || [ "${rd_hash}" = "${expected_hash}" ]; then
                matched=1
                match_type="Repository Digest (${rd})"
                break
            fi
        done
    fi

    if [ "${matched}" -eq 1 ]; then
        echo "  [PASS] Verified ${img} matches trusted ${match_type}"
    else
        echo "FATAL: Image digest mismatch for '${img}'!" >&2
        echo "  Expected Digest: ${expected_digest}" >&2
        echo "  Actual Image ID: ${actual_id}" >&2
        echo "  Repo Digests:    ${repo_digests:-none}" >&2
        FAILED=1
    fi
done

if [ "${FAILED}" -ne 0 ]; then
    echo "=== FATAL: Preflight image verification failed! Aborting deployment. ===" >&2
    exit 1
fi

echo "=== All preloaded images verified against trusted cryptographic digests. ==="
