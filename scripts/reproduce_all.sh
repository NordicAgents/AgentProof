#!/usr/bin/env bash
# reproduce_all.sh — Run the full AgentProof evaluation pipeline.
#
# Prerequisites:
#   pip install -e ".[all-frameworks]"
#   # For GitHub mining (optional): export GITHUB_TOKEN=ghp_...
#
# Usage:
#   bash scripts/reproduce_all.sh

set -euo pipefail

echo "========================================"
echo "AgentProof Evaluation Pipeline"
echo "========================================"

echo ""
echo "Step 1: Build curated corpus"
echo "----------------------------------------"
python scripts/build_corpus.py

echo ""
echo "Step 2: Run defect study (curated corpus)"
echo "----------------------------------------"
python scripts/defect_study.py --corpus corpus/curated --output scripts/defect_results.json

echo ""
echo "Step 3: Generate execution traces"
echo "----------------------------------------"
python scripts/generate_traces.py --corpus corpus/curated --output corpus/traces --n-traces 10

echo ""
echo "Step 4: Evaluate temporal policies"
echo "----------------------------------------"
python scripts/evaluate_policies.py

echo ""
echo "Step 5: Run scalability benchmarks"
echo "----------------------------------------"
python scripts/benchmark_scale.py

echo ""
echo "Step 6: Generate comparison table"
echo "----------------------------------------"
python scripts/generate_comparison_table.py

echo ""
echo "Step 7: Run tests"
echo "----------------------------------------"
python -m pytest tests/ -v

echo ""
echo "========================================"
echo "Pipeline complete. Output files:"
echo "  scripts/defect_results.json"
echo "  corpus/traces/"
echo "  scripts/policy_evaluation_results.json"
echo "  scripts/scaling_results.json"
echo "  paper/generated/comparison_table.tex"
echo "========================================"

# Optional: real-world corpus (requires GITHUB_TOKEN)
if [ -n "${GITHUB_TOKEN:-}" ]; then
    echo ""
    echo "Step 8 (optional): Mine GitHub for real-world workflows"
    echo "----------------------------------------"
    python scripts/scrape_workflows.py --max-per-query 30
    if [ -d "corpus/real_world/graphs" ] && ls corpus/real_world/graphs/*.json 1>/dev/null 2>&1; then
        echo ""
        echo "Step 9 (optional): Defect study on real-world corpus"
        echo "----------------------------------------"
        python scripts/defect_study.py --corpus corpus/real_world/graphs --output scripts/real_world_defect_results.json
    fi
fi
