#!/usr/bin/env python3
"""Matched (paired) v1-vs-v2 extractor comparison.

Answers the reviewer objection that the corrected-extractor comparison in
Table 1 is unmatched: v2 was scored on 115 graphs while v1 was scored on 119,
because ``corrected_fidelity.py`` silently skips ground-truth slugs whose v2
graph does not exist. Every number here is computed on the exact INTERSECTION
of slugs present in BOTH instruments, keyed identically by slug.

Reported:
  (a) matched n (fidelity set and corpus set)
  (b) per-framework + overall node P/R, edge P/R, kind accuracy for v1 AND v2
      on the matched fidelity set
  (c) corpus-wide structural-flag counts (total flagged workflows, per-check,
      incl. unreachable-exit) for v1 AND v2 on the matched corpus set
  (d) every dropped slug logged with a reason (nothing is silently skipped)
  (e) JSON written to corpus/real_world/matched_fidelity.json

Also emits the UNMATCHED numbers side by side so the delta attributable to the
mismatch itself is visible.

Usage:
    uv run python scripts/matched_fidelity.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
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
META_V2 = RW / "metadata_v2.json"
OUT = RW / "matched_fidelity.json"

SELF_REPO_PREFIX = "NordicAgents__AgentProof"

# human_presence is the blunt policy check, not a structural flag.
STRUCTURAL = {
    "exit_reachability",
    "reverse_reachability",
    "dead_ends",
    "router_shape",
    "tool_declarations",
}


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 3) if xs else None


def _agg(rs: list[dict]) -> dict:
    return {
        "n": len(rs),
        "node_precision": _mean([a["node_detection"]["precision"] for a in rs]),
        "node_recall": _mean([a["node_detection"]["recall"] for a in rs]),
        "edge_precision": _mean([a["edge_detection"]["precision"] for a in rs]),
        "edge_recall": _mean([a["edge_detection"]["recall"] for a in rs]),
        "kind_accuracy": _mean([a["node_kind_accuracy"] for a in rs]),
    }


def rekey_recovery(coll: dict[str, list[dict]], v1_slugs: set, v2_slugs: set) -> dict:
    """How many colliding slugs re-keying can rescue as usable v1<->v2 PAIRS.

    v2's file choice is recorded (metadata_v2.json), so every v2 graph re-keys
    exactly. v1's file choice was never recorded -- the miner wrote
    ``<slug>.json`` per file, so the last file with a given basename overwrote
    the earlier ones and the survivor's identity is lost. v1 can only be
    re-keyed where the graph's own ``framework`` field matches exactly one
    candidate. Even then the pair is only usable if v2 mined the SAME file.
    """
    m2 = {}
    if META_V2.exists():
        m2 = {r["slug"]: r for r in json.loads(META_V2.read_text()).get("records", [])}
    v2_rekeyable, v1_rekeyable, pairable, unrecoverable = [], [], [], []
    for slug, cands in coll.items():
        if slug in v2_slugs and m2.get(slug, {}).get("file_path"):
            v2_rekeyable.append(slug)
        if slug not in v1_slugs:
            continue
        fw = json.loads((V1 / f"{slug}.json").read_text()).get("framework")
        match = [c for c in cands if c.get("framework") == fw]
        if len(match) == 1:
            v1_rekeyable.append(slug)
            if m2.get(slug, {}).get("file_path") == match[0]["file_path"]:
                pairable.append(slug)
            else:
                unrecoverable.append({"slug": slug, "reason": "v2_mined_a_different_file",
                                      "v1_inferred_path": match[0]["file_path"],
                                      "v2_path": m2.get(slug, {}).get("file_path")})
        else:
            unrecoverable.append({"slug": slug, "reason": "v1_file_indeterminate",
                                  "n_candidates": len(cands),
                                  "candidate_paths": [c["file_path"] for c in cands]})
    return {
        "n_colliding_slugs": len(coll),
        "n_on_disk_v1": len([s for s in coll if s in v1_slugs]),
        "n_on_disk_v2": len([s for s in coll if s in v2_slugs]),
        "v2_rekeyable_exactly": len(v2_rekeyable),
        "v1_rekeyable_by_framework": len(v1_rekeyable),
        "usable_v1_v2_pairs_recovered": len(pairable),
        "must_drop": len(unrecoverable),
        "unrecoverable_detail": unrecoverable,
    }


def collision_slugs() -> dict[str, list[dict]]:
    """Slugs whose provenance is AMBIGUOUS: the slug ``<repo>__<basename>`` is not
    unique, so more than one (repo, sha, file_path) record claims it.

    ``remine_pinned.load_records`` resolves such a slug first-wins, which can
    re-mine a DIFFERENT source file than v1 mined for the same slug. Those
    graphs are not a v1/v2 instrument comparison at all -- they compare two
    different programs -- so they must be quarantined from any causal claim
    about the extractor.
    """
    seen: dict[str, set] = defaultdict(set)
    detail: dict[str, list[dict]] = defaultdict(list)
    for name in ("metadata.json", "metadata.lg_crew.json"):
        p = RW / name
        if not p.exists():
            continue
        for r in json.loads(p.read_text())["records"]:
            key = (r.get("repo"), r.get("sha"), r.get("file_path"))
            if key not in seen[r["slug"]]:
                seen[r["slug"]].add(key)
                detail[r["slug"]].append({"metadata_file": name, "repo": r.get("repo"),
                                          "sha": r.get("sha"), "file_path": r.get("file_path"),
                                          "framework": r.get("framework")})
    return {s: d for s, d in detail.items() if len(d) > 1}


def structurally_changed(slugs: list[str]) -> list[str]:
    """Slugs whose (node-id set, edge set) differs between v1 and v2."""
    out = []
    for s in slugs:
        g1 = json.loads((V1 / f"{s}.json").read_text())
        g2 = json.loads((V2 / f"{s}.json").read_text())
        k1 = ({n["id"] for n in g1["nodes"]}, {(e["source"], e["target"]) for e in g1["edges"]})
        k2 = ({n["id"] for n in g2["nodes"]}, {(e["source"], e["target"]) for e in g2["edges"]})
        if k1 != k2:
            out.append(s)
    return out


def load_v2_status() -> dict[str, dict]:
    """slug -> remine record (status, repo, sha, framework)."""
    if not META_V2.exists():
        return {}
    recs = json.loads(META_V2.read_text()).get("records", [])
    return {r["slug"]: r for r in recs}


def fidelity(slugs: list[str], graphs_dir: Path, fw_of: dict[str, str]) -> dict:
    """Fidelity of graphs_dir vs ground truth over exactly `slugs` (all must exist)."""
    rows: list[dict] = []
    per_fw: dict[str, list[dict]] = defaultdict(list)
    for slug in slugs:
        ref = json.loads((GT / f"{slug}.json").read_text())
        extracted = json.loads((graphs_dir / f"{slug}.json").read_text())
        acc = compute_accuracy(extracted, ref)
        acc["slug"] = slug
        rows.append(acc)
        per_fw[fw_of[slug]].append(acc)
    return {
        "overall": _agg(rows),
        "per_framework": {fw: _agg(rs) for fw, rs in sorted(per_fw.items())},
        "per_slug": {
            a["slug"]: {
                "node_precision": a["node_detection"]["precision"],
                "node_recall": a["node_detection"]["recall"],
                "edge_precision": a["edge_detection"]["precision"],
                "edge_recall": a["edge_detection"]["recall"],
                "kind_accuracy": a["node_kind_accuracy"],
            }
            for a in rows
        },
    }


def flag_counts(slugs: list[str], graphs_dir: Path) -> dict:
    counts: Counter = Counter()
    flagged: list[str] = []
    errors: list[dict] = []
    for slug in slugs:
        p = graphs_dir / f"{slug}.json"
        try:
            g = graph_from_dict(json.loads(p.read_text()))
            res = run_structural_checks(g, require_human=True)
        except Exception as e:  # never silently skip
            errors.append({"slug": slug, "error": f"{type(e).__name__}: {e}"})
            continue
        raised = False
        for check in res["checks"]:
            if check["check_id"] in STRUCTURAL and check["passed"] is False:
                counts[check["check_id"]] += 1
                raised = True
        if raised:
            flagged.append(slug)
    return {
        "n_graphs": len(slugs) - len(errors),
        "workflows_struct_flagged": len(flagged),
        "by_check": dict(sorted(counts.items())),
        "flagged_slugs": sorted(flagged),
        "errors": errors,
    }


def main() -> int:
    v1_slugs = {p.stem for p in V1.glob("*.json")}
    v2_slugs = {p.stem for p in V2.glob("*.json")}
    gt_slugs = {p.stem for p in GT.glob("*.json")}
    status = load_v2_status()

    # ---------- drop accounting (nothing silent) ----------
    self_repo = sorted(s for s in v1_slugs if s.startswith(SELF_REPO_PREFIX))
    corpus_v1 = {s for s in v1_slugs if not s.startswith(SELF_REPO_PREFIX)}
    corpus_v2 = {s for s in v2_slugs if not s.startswith(SELF_REPO_PREFIX)}
    corpus_matched = sorted(corpus_v1 & corpus_v2)

    dropped: list[dict] = []
    for slug in sorted(corpus_v1 - corpus_v2):
        rec = status.get(slug, {})
        dropped.append({
            "slug": slug,
            "reason": rec.get("status", "no_remine_record"),
            "framework": rec.get("framework", "unknown"),
            "repo": rec.get("repo", ""),
            "sha": rec.get("sha", ""),
            "in_ground_truth": slug in gt_slugs,
        })
    orphan_v2 = sorted(corpus_v2 - corpus_v1)  # present in v2 but not v1 (should be empty)

    drop_reasons = Counter(d["reason"] for d in dropped)
    drop_by_fw = Counter(d["framework"] for d in dropped)
    drop_by_repo = Counter(d["repo"] for d in dropped)
    # Framework labels for the v1 corpus MUST come from each v1 graph's own
    # `framework` field, which the extractor writes from the file it actually
    # parsed. Reading them from `status` (the v2 re-mine records) mislabels every
    # slug-collision case, where v1 (last-wins) and v2 (first-wins) resolved to
    # different files: that bug produced the spurious mix 400/357/115/50 instead
    # of the correct 400/359/113/50.
    def _v1_framework(slug: str) -> str:
        try:
            return json.loads((V1 / f"{slug}.json").read_text()).get("framework", "unknown")
        except OSError:
            return "unknown"

    corpus_fw = Counter(_v1_framework(s) for s in corpus_v1)

    # ---------- matched fidelity set ----------
    gt_corpus = {s for s in gt_slugs if not s.startswith(SELF_REPO_PREFIX)}
    gt_self = sorted(s for s in gt_slugs if s.startswith(SELF_REPO_PREFIX))
    fid_matched = sorted(gt_corpus & corpus_v1 & corpus_v2)
    fid_v1_only = sorted((gt_corpus & corpus_v1) - corpus_v2)
    fid_no_v1 = sorted(gt_corpus - corpus_v1)

    fid_drops = []
    for slug in fid_v1_only:
        rec = status.get(slug, {})
        fid_drops.append({"slug": slug, "reason": rec.get("status", "no_remine_record"),
                          "framework": rec.get("framework", "unknown"), "repo": rec.get("repo", "")})
    for slug in fid_no_v1:
        fid_drops.append({"slug": slug, "reason": "absent_from_v1", "framework": "unknown", "repo": ""})
    for slug in gt_self:
        fid_drops.append({"slug": slug, "reason": "self_repo_excluded", "framework": "self", "repo": ""})

    # framework label taken from the GROUND TRUTH graph so both instruments are
    # bucketed identically (v1/v2 framework fields could in principle differ).
    fw_of: dict[str, str] = {}
    for slug in fid_matched:
        ref = json.loads((GT / f"{slug}.json").read_text())
        fw_of[slug] = ref.get("framework") or status.get(slug, {}).get("framework", "unknown")

    matched_v1 = fidelity(fid_matched, V1, fw_of)
    matched_v2 = fidelity(fid_matched, V2, fw_of)

    # unmatched baselines (what corrected_fidelity.py reports)
    fw_all_v1 = dict(fw_of)
    for slug in fid_v1_only:
        ref = json.loads((GT / f"{slug}.json").read_text())
        fw_all_v1[slug] = ref.get("framework") or status.get(slug, {}).get("framework", "unknown")
    unmatched_v1 = fidelity(sorted(gt_corpus & corpus_v1), V1, fw_all_v1)

    # ---------- matched corpus-wide structural flags ----------
    flags_v1_matched = flag_counts(corpus_matched, V1)
    flags_v2_matched = flag_counts(corpus_matched, V2)
    flags_v1_full = flag_counts(sorted(corpus_v1), V1)  # the paper's unmatched v1 baseline

    out = {
        "note": (
            "Matched v1-vs-v2 comparison. All fidelity and flag numbers are computed on the "
            "exact intersection of slugs present in BOTH instruments (v1 = as-mined graphs/, "
            "v2 = corrected graphs_v2/ re-run at identical pinned SHAs), self-repo excluded. "
            "Every dropped slug is enumerated with a reason."
        ),
        "counts": {
            "v1_graphs_on_disk": len(v1_slugs),
            "v2_graphs_on_disk": len(v2_slugs),
            "self_repo_graphs_excluded": len(self_repo),
            "corpus_v1": len(corpus_v1),
            "corpus_v2": len(corpus_v2),
            "corpus_matched": len(corpus_matched),
            "ground_truth_files": len(gt_slugs),
            "ground_truth_self_repo": len(gt_self),
            "fidelity_matched_n": len(fid_matched),
            "fidelity_v1_unmatched_n": len(gt_corpus & corpus_v1),
        },
        "drops": {
            "corpus_dropped_n": len(dropped),
            "by_reason": dict(drop_reasons),
            "by_framework": dict(drop_by_fw),
            "by_repo": dict(sorted(drop_by_repo.items(), key=lambda kv: -kv[1])),
            "corpus_framework_distribution": dict(corpus_fw),
            "records": dropped,
            "orphan_v2_not_in_v1": orphan_v2,
            "fidelity_set_drops": fid_drops,
        },
        "matched_fidelity": {
            "n": len(fid_matched),
            "v1_asmined": {"overall": matched_v1["overall"], "per_framework": matched_v1["per_framework"]},
            "v2_corrected": {"overall": matched_v2["overall"], "per_framework": matched_v2["per_framework"]},
        },
        "unmatched_fidelity_for_reference": {
            "v1_asmined_n119_style": {"overall": unmatched_v1["overall"],
                                      "per_framework": unmatched_v1["per_framework"]},
        },
        "matched_structural_flags": {
            "n_graphs": len(corpus_matched),
            "v1_asmined": {k: v for k, v in flags_v1_matched.items() if k != "flagged_slugs"},
            "v2_corrected": {k: v for k, v in flags_v2_matched.items() if k != "flagged_slugs"},
            "flagged_only_in_v1": sorted(set(flags_v1_matched["flagged_slugs"]) - set(flags_v2_matched["flagged_slugs"])),
            "flagged_only_in_v2": sorted(set(flags_v2_matched["flagged_slugs"]) - set(flags_v1_matched["flagged_slugs"])),
        },
        "unmatched_structural_flags_for_reference": {
            "v1_asmined_full_corpus": {k: v for k, v in flags_v1_full.items() if k != "flagged_slugs"},
        },
        "per_slug_matched": {
            "v1": matched_v1["per_slug"],
            "v2": matched_v2["per_slug"],
        },
    }

    # ---------- provenance-collision decomposition ----------
    coll = collision_slugs()
    fid_clean = [s for s in fid_matched if s not in coll]
    fid_coll = [s for s in fid_matched if s in coll]
    clean_v1 = fidelity(fid_clean, V1, fw_of)
    clean_v2 = fidelity(fid_clean, V2, fw_of)
    changed_corpus = structurally_changed(corpus_matched)
    out["provenance_collisions"] = {
        "note": ("Slug <repo>__<basename> is not unique. remine_pinned.load_records() resolves "
                 "collisions first-wins, so v2 may re-mine a DIFFERENT file than v1 for the same "
                 "slug. Such graphs compare two different programs, not two instrument versions."),
        "n_colliding_slugs_total": len(coll),
        "n_in_corpus_matched": len([s for s in corpus_matched if s in coll]),
        "n_in_fidelity_matched": len(fid_coll),
        "fidelity_collision_slugs": {s: coll[s] for s in fid_coll},
        "corpus_structurally_changed": {
            "total": len(changed_corpus),
            "collision": len([s for s in changed_corpus if s in coll]),
            "genuine_extractor_change": len([s for s in changed_corpus if s not in coll]),
        },
        "collision_free_fidelity": {
            "n": len(fid_clean),
            "v1_asmined": {"overall": clean_v1["overall"], "per_framework": clean_v1["per_framework"]},
            "v2_corrected": {"overall": clean_v2["overall"], "per_framework": clean_v2["per_framework"]},
        },
        "rekey_recovery": rekey_recovery(coll, v1_slugs, v2_slugs),
    }

    # ---------- collision-free corpus-wide structural flags ----------
    corpus_clean = [s for s in corpus_matched if s not in coll]
    cf_v1 = flag_counts(corpus_clean, V1)
    cf_v2 = flag_counts(corpus_clean, V2)
    out["matched_structural_flags"]["collision_free"] = {
        "n_graphs": len(corpus_clean),
        "n_collision_slugs_removed": len(corpus_matched) - len(corpus_clean),
        "v1_asmined": {k: v for k, v in cf_v1.items() if k != "flagged_slugs"},
        "v2_corrected": {k: v for k, v in cf_v2.items() if k != "flagged_slugs"},
    }

    # ---------- drop-bias check on the excluded colliding fidelity graphs ----------
    # LLM reference-graph reconstruction confidence lives in the workflow output,
    # not in the ground_truth graph files.
    gt_conf: dict[str, str] = {}
    for fname in ("wf_output_combined.json", "wf_output.json"):
        p = RW / fname
        if p.exists():
            for g in json.loads(p.read_text()).get("groundTruth", []):
                gt_conf.setdefault(g["slug"], g.get("confidence", "unknown"))
    strata_all: Counter = Counter(fw_of[s] for s in fid_matched)
    strata_drop: Counter = Counter(fw_of[s] for s in fid_coll)
    out["provenance_collisions"]["fidelity_drop_bias"] = {
        "note": ("Frameworks/strata lost when the 9 colliding graphs are excluded from the "
                 "matched fidelity set. Compare share of the dropped set to share of the "
                 "matched set to judge bias."),
        "matched_115_by_framework": dict(strata_all),
        "dropped_9_by_framework": dict(strata_drop),
        "remaining_106_by_framework": {fw: strata_all[fw] - strata_drop.get(fw, 0)
                                       for fw in sorted(strata_all)},
        "drop_rate_by_framework": {fw: round(strata_drop.get(fw, 0) / strata_all[fw], 3)
                                   for fw in sorted(strata_all)},
        "gt_confidence_of_dropped": dict(Counter(gt_conf.get(s, "unknown") for s in fid_coll)),
        "gt_confidence_of_matched": dict(Counter(gt_conf.get(s, "unknown") for s in fid_matched)),
    }
    OUT.write_text(json.dumps(out, indent=1))
    OUT.write_text(json.dumps(out, indent=1))

    # ---------------- report ----------------
    def line(tag, d):
        o = d["overall"]
        return (f"  {tag:14s} n={o['n']:3d}  nodeP={o['node_precision']}  nodeR={o['node_recall']}"
                f"  edgeP={o['edge_precision']}  edgeR={o['edge_recall']}  kindAcc={o['kind_accuracy']}")

    print("=" * 78)
    print("DROP ACCOUNTING (self-repo excluded)")
    print(f"  corpus v1={len(corpus_v1)}  v2={len(corpus_v2)}  matched={len(corpus_matched)}  "
          f"dropped={len(dropped)}  orphan_v2={len(orphan_v2)}")
    print(f"  drop reasons          : {dict(drop_reasons)}")
    print(f"  drop by framework     : {dict(drop_by_fw)}")
    print(f"  corpus by framework   : {dict(corpus_fw)}")
    print("  dropped slugs:")
    for d in dropped:
        gtm = "  [IN GROUND TRUTH]" if d["in_ground_truth"] else ""
        print(f"    {d['reason']:18s} {d['framework']:10s} {d['slug']}{gtm}")
    print("  fidelity-set exclusions:")
    for d in fid_drops:
        print(f"    {d['reason']:20s} {d['slug']}")

    print("=" * 78)
    print(f"MATCHED FIDELITY (n={len(fid_matched)}, identical slug set for both instruments)")
    print(line("v1 as-mined", matched_v1))
    print(line("v2 corrected", matched_v2))
    print(f"  [unmatched v1 baseline for reference, n={unmatched_v1['overall']['n']}]")
    print(line("v1 unmatched", unmatched_v1))
    print("  per-framework (matched):")
    hdr = f"    {'framework':12s} {'n':>4s} {'nodeP':>7s} {'nodeR':>7s} {'edgeP':>7s} {'edgeR':>7s} {'kindAcc':>8s}"
    for tag, d in (("v1", matched_v1), ("v2", matched_v2)):
        print(f"  -- {tag} --")
        print(hdr)
        for fw, a in d["per_framework"].items():
            print(f"    {fw:12s} {a['n']:4d} {a['node_precision']:7} {a['node_recall']:7} "
                  f"{a['edge_precision']:7} {a['edge_recall']:7} {a['kind_accuracy']:8}")

    print("=" * 78)
    print(f"MATCHED CORPUS-WIDE STRUCTURAL FLAGS (n={len(corpus_matched)} graphs, same slugs both sides)")
    print(f"  v1 flagged workflows: {flags_v1_matched['workflows_struct_flagged']}")
    print(f"  v2 flagged workflows: {flags_v2_matched['workflows_struct_flagged']}")
    checks = sorted(set(flags_v1_matched["by_check"]) | set(flags_v2_matched["by_check"]))
    print(f"    {'check':22s} {'v1':>5s} {'v2':>5s}")
    for c in checks:
        print(f"    {c:22s} {flags_v1_matched['by_check'].get(c,0):5d} {flags_v2_matched['by_check'].get(c,0):5d}")
    print(f"  [unmatched v1 full-corpus baseline: n={flags_v1_full['n_graphs']}, "
          f"flagged={flags_v1_full['workflows_struct_flagged']}, by_check={flags_v1_full['by_check']}]")
    if flags_v1_matched["errors"] or flags_v2_matched["errors"]:
        print(f"  ERRORS v1={flags_v1_matched['errors']} v2={flags_v2_matched['errors']}")
    print("=" * 78)
    pc = out["provenance_collisions"]
    print("PROVENANCE COLLISIONS (slug not unique -> v2 may re-mine a different file)")
    print(f"  colliding slugs total={pc['n_colliding_slugs_total']}  "
          f"in matched corpus={pc['n_in_corpus_matched']}  in matched fidelity set={pc['n_in_fidelity_matched']}")
    cs = pc["corpus_structurally_changed"]
    print(f"  corpus graphs structurally changed v1->v2: {cs['total']} "
          f"({cs['collision']} collision-contaminated, {cs['genuine_extractor_change']} genuine)")
    print(f"  COLLISION-FREE matched fidelity (n={pc['collision_free_fidelity']['n']}):")
    print(line("v1 as-mined", pc["collision_free_fidelity"]["v1_asmined"]))
    print(line("v2 corrected", pc["collision_free_fidelity"]["v2_corrected"]))
    print("    per-framework edge recall v1 -> v2 (collision-free):")
    cf = pc["collision_free_fidelity"]
    for fw in sorted(cf["v1_asmined"]["per_framework"]):
        a = cf["v1_asmined"]["per_framework"][fw]; b = cf["v2_corrected"]["per_framework"][fw]
        mark = "" if a["edge_recall"] == b["edge_recall"] else "   <-- CHANGED"
        print(f"      {fw:12s} n={a['n']:3d}  {a['edge_recall']} -> {b['edge_recall']}{mark}")
    rk = pc["rekey_recovery"]
    print("  RE-KEY RECOVERY (repo+full-path key; no re-mining):")
    print(f"    colliding slugs={rk['n_colliding_slugs']}  on-disk v1={rk['n_on_disk_v1']}  on-disk v2={rk['n_on_disk_v2']}")
    print(f"    v2 re-keyable exactly           : {rk['v2_rekeyable_exactly']}")
    print(f"    v1 re-keyable (framework unique): {rk['v1_rekeyable_by_framework']}")
    print(f"    usable v1<->v2 PAIRS recovered  : {rk['usable_v1_v2_pairs_recovered']}")
    print(f"    must drop                       : {rk['must_drop']}")

    print("=" * 78)
    cfree = out["matched_structural_flags"]["collision_free"]
    print(f"COLLISION-FREE MATCHED CORPUS FLAGS (n={cfree['n_graphs']}, "
          f"{cfree['n_collision_slugs_removed']} collision slugs removed)")
    print(f"  v1 flagged workflows: {cfree['v1_asmined']['workflows_struct_flagged']}")
    print(f"  v2 flagged workflows: {cfree['v2_corrected']['workflows_struct_flagged']}")
    ck = sorted(set(cfree["v1_asmined"]["by_check"]) | set(cfree["v2_corrected"]["by_check"]))
    print(f"    {'check':22s} {'v1':>5s} {'v2':>5s}")
    for c in ck:
        print(f"    {c:22s} {cfree['v1_asmined']['by_check'].get(c,0):5d} "
              f"{cfree['v2_corrected']['by_check'].get(c,0):5d}")

    print("=" * 78)
    print(f"PUBLISHABLE TABLE 1 (collision-free matched, n={cf['n']})")
    print(f"  {'Framework':12s} {'n':>4s} | {'EdgeP v1':>9s} {'EdgeR v1':>9s} {'Kind v1':>8s} "
          f"| {'EdgeP v2':>9s} {'EdgeR v2':>9s} {'Kind v2':>8s}")
    for fw in sorted(cf["v1_asmined"]["per_framework"]):
        a = cf["v1_asmined"]["per_framework"][fw]; b = cf["v2_corrected"]["per_framework"][fw]
        print(f"  {fw:12s} {a['n']:4d} | {a['edge_precision']:9} {a['edge_recall']:9} {a['kind_accuracy']:8} "
              f"| {b['edge_precision']:9} {b['edge_recall']:9} {b['kind_accuracy']:8}")
    a = cf["v1_asmined"]["overall"]; b = cf["v2_corrected"]["overall"]
    print(f"  {'OVERALL':12s} {a['n']:4d} | {a['edge_precision']:9} {a['edge_recall']:9} {a['kind_accuracy']:8} "
          f"| {b['edge_precision']:9} {b['edge_recall']:9} {b['kind_accuracy']:8}")
    print(f"  node detection overall: v1 P={a['node_precision']} R={a['node_recall']}  |  "
          f"v2 P={b['node_precision']} R={b['node_recall']}")

    print("  DROP BIAS of the 9 excluded colliding graphs:")
    fb = pc["fidelity_drop_bias"]
    print(f"    {'framework':12s} {'matched115':>11s} {'dropped':>8s} {'remaining':>10s} {'droprate':>9s}")
    for fw in sorted(fb["matched_115_by_framework"]):
        print(f"    {fw:12s} {fb['matched_115_by_framework'][fw]:11d} "
              f"{fb['dropped_9_by_framework'].get(fw,0):8d} {fb['remaining_106_by_framework'][fw]:10d} "
              f"{fb['drop_rate_by_framework'][fw]:9}")
    print(f"    GT confidence dropped={fb['gt_confidence_of_dropped']}  matched={fb['gt_confidence_of_matched']}")
    print("=" * 78)
    print(f"JSON written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
