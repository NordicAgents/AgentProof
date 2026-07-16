#!/usr/bin/env bash
#
# reproduce_cegar.sh — one command to reproduce the offline AgentProof-CEGAR
# experiments (plan §7: E0, E2, E3, E5, E8) into scripts/cegar/results/.
#
# HONESTY: only the offline / solver-only arms run here. The LLM-repair
# baselines (E3), the human study (E6), and the real-defect slices require a
# model / recruited participants / real repositories and are NOT executed; the
# individual scripts print that plainly and never fabricate numbers for them.
#
# Usage:  bash scripts/cegar/reproduce_cegar.sh
#
set -euo pipefail

# Resolve the repo root from this script's location so it runs from anywhere.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

# Prefer the project venv python; fall back to python3 on PATH.
if [[ -x "${REPO_ROOT}/.venv/bin/python" ]]; then
  PY="${REPO_ROOT}/.venv/bin/python"
else
  PY="python3"
fi

RESULTS_DIR="${SCRIPT_DIR}/results"
mkdir -p "${RESULTS_DIR}"

echo "############################################################"
echo "# AgentProof-CEGAR — offline experiment reproduction"
echo "# repo:    ${REPO_ROOT}"
echo "# python:  ${PY}"
echo "# results: ${RESULTS_DIR}"
echo "############################################################"
echo

run_step() {
  local name="$1"; shift
  echo "------------------------------------------------------------"
  echo ">>> ${name}"
  echo "------------------------------------------------------------"
  "${PY}" "$@"
  echo
}

run_step "E0  semantic conformance" "${SCRIPT_DIR}/e0_semantic_conformance.py"
run_step "E2  tri-valued diagnosis" "${SCRIPT_DIR}/e2_diagnosis.py"
run_step "E3  verified repair (solver-only)" "${SCRIPT_DIR}/e3_repair.py"
run_step "E5  static/runtime partition" "${SCRIPT_DIR}/e5_partition.py"
run_step "E8  ablations and scalability" "${SCRIPT_DIR}/e8_ablation.py"

echo "############################################################"
echo "# DONE. JSON results written to:"
echo "#   ${RESULTS_DIR}"
ls -1 "${RESULTS_DIR}"/*.json 2>/dev/null | sed 's/^/#   /' || true
echo "############################################################"
