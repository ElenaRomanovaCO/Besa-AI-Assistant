#!/usr/bin/env bash
# =============================================================================
# build_layer.sh — Build the Lambda dependency layer
#
# Installs all packages from backend/requirements.txt into backend/layer/python/
# so CDK can package them as a Lambda Layer (compatible with Python 3.12 / x86_64).
#
# Usage (run from project root OR backend/):
#   bash backend/scripts/build_layer.sh           # default: Docker build (recommended)
#   bash backend/scripts/build_layer.sh --local   # local pip install (Linux only)
#
# The Docker build ensures binary packages (PyNaCl, cryptography, etc.) are
# compiled for the Lambda runtime (Amazon Linux 2023 / x86_64), not your host OS.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
LAYER_DIR="${BACKEND_DIR}/layer"
PYTHON_DIR="${LAYER_DIR}/python"
REQUIREMENTS="${BACKEND_DIR}/requirements.txt"

BUILD_MODE="${1:-}"

echo "============================================"
echo " BeSa AI — Lambda Layer Builder"
echo " Backend : ${BACKEND_DIR}"
echo " Output  : ${PYTHON_DIR}"
echo " Mode    : ${BUILD_MODE:-docker (default)}"
echo "============================================"

# Clean previous build
echo "[1/3] Cleaning previous layer build..."
rm -rf "${PYTHON_DIR}"
mkdir -p "${PYTHON_DIR}"

if [[ "${BUILD_MODE}" == "--local" ]]; then
    # -----------------------------------------------------------------------
    # Local build — fast but requires Linux x86_64 (or native arm64 Lambda)
    # -----------------------------------------------------------------------
    echo "[2/3] Installing packages locally..."
    pip install \
        --requirement "${REQUIREMENTS}" \
        --target "${PYTHON_DIR}" \
        --upgrade \
        --no-cache-dir \
        --quiet
else
    # -----------------------------------------------------------------------
    # Docker build — cross-compiles for Amazon Linux 2023 / x86_64
    # Required for packages with C extensions: PyNaCl, cryptography, etc.
    # -----------------------------------------------------------------------
    if ! command -v docker &>/dev/null; then
        echo "ERROR: Docker not found. Install Docker or use --local flag."
        exit 1
    fi

    echo "[2/3] Installing packages via Docker (python:3.12-slim / linux/amd64)..."
    docker run --rm \
        --platform linux/amd64 \
        -v "${REQUIREMENTS}:/requirements.txt:ro" \
        -v "${PYTHON_DIR}:/layer/python" \
        python:3.12-slim \
        pip install \
            --requirement /requirements.txt \
            --target /layer/python \
            --upgrade \
            --no-cache-dir \
            --quiet
fi

# Remove packages already provided by Lambda runtime (saves layer space)
# boto3 and botocore are included in Python 3.12 runtime at 1.34+
# Uncomment if layer size exceeds 250 MB unzipped limit:
# echo "Pruning Lambda-provided packages..."
# rm -rf "${PYTHON_DIR}/boto3" "${PYTHON_DIR}/botocore" "${PYTHON_DIR}/boto3-*.dist-info"

echo "[3/3] Layer build complete."
echo ""
echo "Layer contents:"
du -sh "${PYTHON_DIR}" 2>/dev/null || true
echo ""
echo "Run 'cdk deploy' from infrastructure/ to deploy."
