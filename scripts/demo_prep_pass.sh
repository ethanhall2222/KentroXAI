#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

export DEMO_CONFIG_PATH="${REPO_ROOT}/configs/demo_pass_config.yaml"
export DEMO_CONTEXT_PATH="${REPO_ROOT}/configs/demo_context.json"
export DEMO_ALIAS_NAME="${DEMO_ALIAS_NAME:-latest-pass}"
export DEMO_PROMPT="${DEMO_PROMPT:-Summarize the release checklist for a governed AI system.}"
export DEMO_MODEL_OUTPUT="${DEMO_MODEL_OUTPUT:-Use the approved release checklist, confirm evidence completeness, and route final approval to human review.}"

"${REPO_ROOT}/scripts/demo_prep.sh"
