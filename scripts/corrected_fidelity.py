#!/usr/bin/env python3
"""Re-score extractor fidelity with the corrected instrument (graphs_v2).

Compares the as-mined extractor (corpus/real_world/graphs, "v1") and the
corrected extractor run at the same pinned SHAs (corpus/real_world/graphs_v2,
"v2") against the same LLM reference graphs (corpus/real_world/ground_truth),
applying the paper's reported self-repo exclusion. Also reports how many mined
structural flags change between v1 and v2.

Output: corpus/real_world/corrected_fidelity.json + printed summary.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from extractor_accuracy import compute_accuracy  # noqa: E402
from agentproof.graph.model import graph_from_dict  # noqa: E402
from agentproof.verify import run_structural_checks  # noqa: E402

RW = ROOT / "corpus" / "real_world"
GT = RW / "ground_truth"
V1 = RW / "graphs"
V2 = RW / "graphs_v2"
SELF_REPO_PREFIX = "NordicAgents__AgentProof"


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def score(graphs_dir: Path) -> dict:
    """Mean fidelity of graphs_dir vs ground_truth, self-repo excluded."""
    rows = []
    per_fw: dict[str, list] = defaultdict(list)
    for gt_path in sorted(GT.glob("*.json")):
        slug = gt_path.stem
        if slug.startswith(SELF_REPO_PREFIX):
            continue
        ex_path = graphs_dir / f"{slug}.json"
        if not ex_path.exists():
            continue  # v2 may lack a graph the instrument now drops; counted separately
        ref = json.loads(gt_path.read_text())
        extracted = json.loads(ex_path.read_text())
        acc = compute_accuracy(extracted, ref)
        acc["slug"] = slug
        fw = ref.get("framework", "unknown")
        rows.append((fw, acc))
        per_fw[fw].append(acc)

    def agg(rs):
        return {
            "n": len(rs),
            "node_precision": _mean([a["node_detection"]["precision"] for a in rs]),
            "node_recall": _mean([a["node_detection"]["recall"] for a in rs]),
            "edge_precision": _mean([a["edge_detection"]["precision"] for a in rs]),
            "edge_recall": _mean([a["edge_detection"]["recall"] for a in rs]),
            "kind_accuracy": _mean([a["node_kind_accuracy"] for a in rs]),
        }

    return {
        "overall": agg([a for _, a in rows]),
        "per_framework": {fw: agg(rs) for fw, rs in sorted(per_fw.items())},
        "n_scored": len(rows),
    }


STRUCTURAL = {"exit_reachability", "reverse_reachability", "dead_ends",
              "router_shape", "tool_declarations"}


def flag_counts(graphs_dir: Path, slugs: list[str]) -> dict:
    """Structural flags raised over the given slugs' graphs (human_presence excluded:
    it is the blunt policy check, not a structural flag)."""
    counts: dict[str, int] = defaultdict(int)
    workflows_struct_flagged = 0
    n = 0
    for slug in slugs:
        p = graphs_dir / f"{slug}.json"
        if not p.exists():
            continue
        n += 1
        g = graph_from_dict(json.loads(p.read_text()))
        res = run_structural_checks(g, require_human=True)
        raised = False
        for check in res["checks"]:
            if check["check_id"] in STRUCTURAL and check["passed"] is False:
                counts[check["check_id"]] += 1
                raised = True
        if raised:
            workflows_struct_flagged += 1
    return {"n_graphs": n, "workflows_struct_flagged": workflows_struct_flagged,
            "by_check": dict(counts)}


def main() -> int:
    fid_v1 = score(V1)
    fid_v2 = score(V2)

    # Flag deltas over the full mined corpus (all slugs present in v1).
    all_slugs = sorted(p.stem for p in V1.glob("*.json") if not p.stem.startswith(SELF_REPO_PREFIX))
    flags_v1 = flag_counts(V1, all_slugs)
    flags_v2 = flag_counts(V2, all_slugs)

    out = {
        "note": ("v1 = as-mined extractor (paper Table 1); v2 = corrected extractor "
                 "(path_map 3-positional + LoopAgent fixes) re-run at identical pinned SHAs. "
                 "Fidelity vs the same LLM reference graphs, self-repo excluded."),
        "fidelity_v1_asmined": fid_v1,
        "fidelity_v2_corrected": fid_v2,
        "flags_v1_asmined": flags_v1,
        "flags_v2_corrected": flags_v2,
    }
    (RW / "corrected_fidelity.json").write_text(json.dumps(out, indent=1))

    def fmt(d):
        o = d["overall"]
        return f"n={d['n_scored']:3d}  edgeP={o['edge_precision']}  edgeR={o['edge_recall']}  kindAcc={o['kind_accuracy']}"
    print("FIDELITY vs reference graphs (self-repo excluded):")
    print("  v1 as-mined :", fmt(fid_v1))
    print("  v2 corrected:", fmt(fid_v2))
    print("  per-framework edge recall (v1 -> v2):")
    for fw in sorted(set(fid_v1["per_framework"]) | set(fid_v2["per_framework"])):
        r1 = fid_v1["per_framework"].get(fw, {}).get("edge_recall")
        r2 = fid_v2["per_framework"].get(fw, {}).get("edge_recall")
        n2 = fid_v2["per_framework"].get(fw, {}).get("n")
        print(f"    {fw:10s} {r1} -> {r2}  (n={n2})")
    print("STRUCTURAL FLAGS over mined corpus:")
    print(f"  v1: {flags_v1['workflows_struct_flagged']} workflows struct-flagged (n={flags_v1['n_graphs']}), by_check={flags_v1['by_check']}")
    print(f"  v2: {flags_v2['workflows_struct_flagged']} workflows struct-flagged (n={flags_v2['n_graphs']}), by_check={flags_v2['by_check']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
