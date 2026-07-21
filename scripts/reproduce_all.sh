#!/usr/bin/env bash
# reproduce_all.sh — Run the full AgentProof evaluation pipeline.
#
# Two stages:
#   A. Curated pipeline (steps 1-7).  Fully self-contained: no network, no
#      credentials.  These regenerate every curated-corpus number in the paper.
#   B. Real-world pipeline (steps 8-20).  Recomputes the mined-corpus analyses
#      from artifacts already committed under corpus/real_world/.
#
# What this script does NOT reproduce (by design, announced loudly at runtime):
#   - GitHub mining (needs network + GITHUB_TOKEN)
#   - The LLM reconstruction / triage passes (scripts/wf_run*.js,
#     wf_validate_triage.js): non-deterministic and network-bound.  Their raw
#     outputs are committed (corpus/real_world/wf_output*.json,
#     gt_triage_results.json) and consumed here, so the ANALYSES reproduce
#     deterministically even though the LLM passes themselves do not.
#
# Prerequisites:
#   uv sync                    # or: pip install -e ".[all-frameworks]"
#   export GITHUB_TOKEN=ghp_...   # optional, only for the mining steps
#
# Usage:
#   bash scripts/reproduce_all.sh

set -uo pipefail

PY="${PY:-uv run python}"
FAILED=()
SKIPPED=()
PASSED=()

banner() {
    echo ""
    echo "=================================================================="
    echo "$1"
    echo "=================================================================="
}

step() {
    echo ""
    echo "------------------------------------------------------------------"
    echo "STEP $1"
    echo "------------------------------------------------------------------"
}

# skip <step-label> <reason>
skip() {
    echo ""
    echo "##################################################################"
    echo "## SKIPPED: $1"
    echo "## REASON : $2"
    echo "##################################################################"
    SKIPPED+=("$1 — $2")
}

# run <step-label> <command...>
run() {
    local label="$1"; shift
    step "$label"
    if "$@"; then
        PASSED+=("$label")
    else
        echo ""
        echo "!!! FAILED: $label"
        FAILED+=("$label")
    fi
}

# need_file <step-label> <path> — returns 1 (and records a loud skip) if absent
need_file() {
    local label="$1" path="$2"
    if [ ! -e "$path" ]; then
        skip "$label" "required input not found: $path"
        return 1
    fi
    return 0
}

banner "AgentProof Evaluation Pipeline"
echo "python: $($PY -c 'import sys; print(sys.version.split()[0])' 2>/dev/null || echo UNKNOWN)"
echo "repo  : $(pwd)"

# ==================================================================
# STAGE A — curated pipeline (self-contained)
# ==================================================================
banner "STAGE A — curated corpus (no network, no credentials)"

run "1. Build curated corpus" \
    $PY scripts/build_corpus.py

run "2. Defect study (curated corpus)" \
    $PY scripts/defect_study.py --corpus corpus/curated --output scripts/defect_results.json

run "3. Generate execution traces" \
    $PY scripts/generate_traces.py --corpus corpus/curated --output corpus/traces --n-traces 10

run "4. Evaluate temporal policies" \
    $PY scripts/evaluate_policies.py

run "5. Scalability benchmarks" \
    $PY scripts/benchmark_scale.py

run "6. Comparison table" \
    $PY scripts/generate_comparison_table.py

run "7. Test suite" \
    $PY -m pytest tests/ -q

# ==================================================================
# STAGE B — real-world pipeline (from committed artifacts)
# ==================================================================
banner "STAGE B — real-world mined corpus"

RW=corpus/real_world

# ---- 8. Mining (network + credentials) ---------------------------
if [ -z "${GITHUB_TOKEN:-}" ]; then
    skip "8. GitHub mining (mine_github_gh.py)" \
         "GITHUB_TOKEN is not set. Mining needs network access and a GitHub API token. The mined corpus is already committed at $RW/graphs/ (930 files; 922 after the self-repo exclusion), so every downstream step below still runs."
elif [ "${SKIP_MINING:-0}" = "1" ]; then
    skip "8. GitHub mining (mine_github_gh.py)" \
         "SKIP_MINING=1 was set explicitly."
else
    run "8. Mine GitHub for real-world workflows" \
        $PY scripts/mine_github_gh.py --search --clone --extract
fi

# ---- 9. Re-mine at pinned SHAs (network) -------------------------
if [ -z "${GITHUB_TOKEN:-}" ]; then
    skip "9. Re-mine at pinned SHAs (remine_pinned.py)" \
         "GITHUB_TOKEN is not set. This step re-fetches every record at its pinned SHA to build graphs_v2/. Its output is already committed at $RW/graphs_v2/ (912 graphs) and $RW/metadata_v2.json, so the v1-vs-v2 comparisons below still run."
else
    run "9. Re-mine at pinned SHAs (corrected extractor)" \
        $PY scripts/remine_pinned.py
fi

# ---- 10. LLM validation passes (non-deterministic) ---------------
skip "10. LLM reconstruction + triage (wf_run.js / wf_run_v2.js / wf_validate_triage.js)" \
     "These are non-deterministic, network-bound LLM agent passes and are NOT re-executed by this script. Their raw outputs are committed ($RW/wf_output.json, wf_output_v2.json, wf_output_combined.json, gt_triage_results.json, gt_flags_for_triage.json) and are consumed by the steps below. NOTE: the 119-workflow sample these scripts use is a hard-coded slug list with no seed and no documented selection rule — see CLAIMS_AUDIT.md 8.4."

# ---- 11. Defect study on the mined corpus ------------------------
if need_file "11. Defect study (real-world corpus)" "$RW/graphs"; then
    run "11. Defect study (real-world corpus)" \
        $PY scripts/defect_study.py --corpus "$RW/graphs" --output "$RW/defect_results.json"
fi

# ---- 12. Aggregate the LLM workflow output -----------------------
if need_file "12. Aggregate real-world validation (aggregate_realworld.py)" "$RW/wf_output_combined.json"; then
    run "12. Aggregate real-world validation" \
        $PY scripts/aggregate_realworld.py --workflow-output "$RW/wf_output_combined.json"
fi

# ---- 13. Revision analyses (census, exclusions, clustered CIs) ---
run "13. Revision analyses (census + clustered CIs)" \
    $PY scripts/revision_analyses.py

# ---- 14. Confidence intervals ------------------------------------
if need_file "14. Confidence intervals (compute_cis.py)" "$RW/validated_results.json"; then
    run "14. Confidence intervals" \
        $PY scripts/compute_cis.py --validated "$RW/validated_results.json" \
                                   --output "$RW/confidence_intervals.json"
fi

# ---- 15. Monitor pruning -----------------------------------------
# Curated: deliberately run WITHOUT --corpus-kind curated. The script would then
# assert trace-conservatism (assume_trace_conservative=true), which is defensible
# for authored-with-code graphs but is a strictly weaker premise. The committed
# artifact the paper cites was produced under the conservative default, and the
# headline is identical either way (237/270 certified-sound), so we keep the
# stronger setting.
run "15a. Monitor pruning (curated, 18x15=270)" \
    $PY scripts/monitor_pruning.py --corpus corpus/curated \
        --output "$RW/monitor_pruning_curated.json"

# Mined: MUST apply the 8-file self-repo exclusion, or the denominator becomes
# 930x15=13950 and disagrees with the 922-workflow corpus census.
run "15b. Monitor pruning (mined, self-repo excluded, 922x15=13830)" \
    $PY scripts/monitor_pruning.py --corpus "$RW/graphs" \
        --exclude-prefix NordicAgents__AgentProof \
        --output "$RW/monitor_pruning_922.json"

# ---- 16. Risk-aware gate -----------------------------------------
run "16a. Risk-aware gate (curated)" \
    $PY scripts/risk_aware_gate.py --corpus corpus/curated \
        --output "$RW/risk_aware_gate_curated.json"

run "16b. Risk-aware gate (mined, self-repo excluded, n=922)" \
    $PY scripts/risk_aware_gate.py --corpus "$RW/graphs" \
        --exclude-prefix NordicAgents__AgentProof \
        --output "$RW/risk_aware_gate_922.json"

# ---- 17. Runtime fidelity (needs the framework packages installed) ----
# This step imports and EXECUTES real workflows, so it needs the optional
# framework extras (langgraph, crewai, autogen, adk), not just AgentProof.
if $PY -c 'import langgraph' >/dev/null 2>&1; then
    run "17. Runtime fidelity (AST vs runtime traces)" \
        $PY scripts/runtime_fidelity.py
else
    skip "17. Runtime fidelity (runtime_fidelity.py)" \
         "the 'langgraph' package is not installed. This step instantiates and executes real workflows to compare runtime graphs against AST-extracted ones, so it needs the framework extras: pip install -e '.[all-frameworks]' (or uv sync --extra all-frameworks). Its output is already committed at $RW/runtime_fidelity.json (n_runnable=5, 2 id-aligned)."
fi

# ---- 18. v1-vs-v2 instrument comparisons -------------------------
if need_file "18a. Corrected-instrument fidelity (corrected_fidelity.py)" "$RW/graphs_v2"; then
    run "18a. Corrected-instrument fidelity (v2)" \
        $PY scripts/corrected_fidelity.py
fi

if need_file "18b. Matched + collision-free fidelity (matched_fidelity.py)" "$RW/graphs_v2"; then
    run "18b. Matched + collision-free fidelity (v1 vs v2)" \
        $PY scripts/matched_fidelity.py
fi

# ---- 19. Error decomposition -------------------------------------
run "19. Error decomposition (effect vs provenance)" \
    $PY scripts/error_decomposition.py

# ---- 20. Reviewer analyses, pruning experiment, sensitivity ------
run "20a. Reviewer analyses (estimands, post-strat, Fisher, PPV)" \
    $PY scripts/reviewer_analyses.py

run "20b. Path-sensitive pruning experiment" \
    $PY scripts/pruning_experiment.py

run "20c. Sensitivity analyses (dedup, confidence, strata)" \
    $PY scripts/sensitivity_analyses.py

# ==================================================================
# Summary
# ==================================================================
banner "PIPELINE SUMMARY"

echo "PASSED (${#PASSED[@]}):"
for s in "${PASSED[@]:-}"; do [ -n "$s" ] && echo "  ✓ $s"; done

if [ "${#SKIPPED[@]}" -gt 0 ]; then
    echo ""
    echo "SKIPPED (${#SKIPPED[@]}):"
    for s in "${SKIPPED[@]}"; do echo "  ⊘ $s"; done
fi

if [ "${#FAILED[@]}" -gt 0 ]; then
    echo ""
    echo "FAILED (${#FAILED[@]}):"
    for s in "${FAILED[@]}"; do echo "  ✗ $s"; done
    echo ""
    echo "Pipeline completed WITH FAILURES."
    exit 1
fi

echo ""
echo "Key output files:"
echo "  scripts/defect_results.json          scripts/scaling_results.json"
echo "  scripts/policy_evaluation_results.json"
echo "  corpus/traces/"
echo "  $RW/validated_results.json           $RW/revision_analyses.json"
echo "  $RW/confidence_intervals.json        $RW/reviewer_analyses.json"
echo "  $RW/monitor_pruning_curated.json     $RW/monitor_pruning_922.json"
echo "  $RW/risk_aware_gate_curated.json     $RW/risk_aware_gate_922.json"
echo "  $RW/corrected_fidelity.json          $RW/matched_fidelity.json"
echo "  $RW/error_decomposition.json         $RW/pruning_experiment.json"
echo "  $RW/sensitivity_analyses.json        $RW/runtime_fidelity.json"
echo "  papers/paper1/generated/comparison_table.tex"
echo ""
echo "Pipeline complete — no failures."
