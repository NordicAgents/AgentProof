#!/usr/bin/env python3
"""Symmetric FALSE-POSITIVE and FALSE-NEGATIVE decomposition over four causes.

`scripts/error_decomposition.py` attributes non-actionable flags to
EXTRACTOR / POLICY-SPEC / LABEL but records an explicit gap: CHECKER is *not
separable* from POLICY-SPEC, because the committed triage vocabulary asked
"is this a real defect?", not "whose fault is this flag?".  It also decomposes
only false POSITIVES; false negatives were reported anecdotally.

This script closes both gaps without inventing new labels, using one
prospectively specified mechanical rule per side. Nothing here re-reads source code:
every input is a committed artifact, so the whole decomposition is replayable.

---------------------------------------------------------------------------
FALSE POSITIVES -- the survival test
---------------------------------------------------------------------------
For each triaged flag (slug s, check C) judged NON-ACTIONABLE:

  R1  Re-run C on the source-reconstructed reference graph GT(s).
      If C does NOT fire on GT(s)                      -> EXTRACTOR
      The oracle graph removes the flag, so the flag was a property of the
      extraction, not of the check.

  If C DOES fire on GT(s) -- the flagged condition holds of a faithful graph
  and the flag is still not actionable -- the fault is check-side:

  R2  C is a STRUCTURAL check (dead_ends, exit_reachability,
      reverse_reachability, router_shape, tool_declarations)   -> CHECKER
      A structural check is a claim about topology alone; it has no
      per-workflow applicability parameter to misfire on.  If the topology is
      faithful and the finding is still not a defect, the check's decision
      procedure is wrong for that framework's semantics (e.g. it does not
      model LangGraph's interrupt/multi-turn re-entry, ADK LoopAgent
      back-edges, or runtime-bound tool registries).

  R3  C is a POLICY check (human_presence, human_gate_coverage) -> POLICY_SPEC
      EXCEPT when GT(s) contains a node of kind `human`, in which case the
      check's predicate contradicts evidence already present in the faithful
      graph                                                    -> CHECKER

  R4  triage label `arguable`                                  -> LABEL
  R5  triage label `real_defect`                               -> ACTIONABLE
      (excluded from the non-actionable denominator)

R4/R5 are applied BEFORE R1-R3: a disputed label is a label error whatever the
graph says.

VALIDITY GUARD.  R1-R3 presume the reference graph is correct for the predicate
under test.  Two committed sources record where it is not, and both are checked
BEFORE R1 fires:

  G-a  the GT triage pass labelled this (slug, check) flag `gt_error`, i.e. the
       reconstruction itself misrepresents the source; or
  G-b  the check is a policy check whose verdict turns on a node typed `human`
       in the reference graph that the HGP-1 audit found NON-DISCHARGING
       (placebo, inert, or non-dominating).

When the guard trips the survival test is not evidence about the checker, and
the flag is attributed REFERENCE_ERROR: a model error like EXTRACTOR, but one
the source reconstruction shares, so it cannot be blamed on this extractor. Reporting it
as a separate cause rather than folding it into either side is the point --- it
measures how often the source reconstruction is itself wrong.

---------------------------------------------------------------------------
FALSE NEGATIVES -- the miss test
---------------------------------------------------------------------------
The source-audited defect set is the HGP-1 audit's 12 human-gate violations plus
the 1 structural defect.  For each, we ask why the as-mined pipeline (v1 graph
+ risk-aware `human_gate_coverage`) did not report it:

  F1  the v1 graph declares NO tool matching the sensitivity lexicon
                                                               -> EXTRACTOR
      The effect is invisible at the declaration level the check reads (the
      tool->llm kind error), so no policy could have fired.

  F2  a sensitive tool IS declared, but the check cleared the workflow because
      a node typed `human` exists AND that gate is on the audited
      non-discharging list (placebo / inert / non-dominating)  -> CHECKER
      The check's predicate reads node KIND, not whether the body can block.

  F3  a sensitive tool IS declared and no gate excuse applies  -> POLICY_SPEC
      The lexicon's notion of "sensitive" does not cover the tool.

Output: corpus/real_world/fp_fn_decomposition.json
Run:    uv run python scripts/fp_fn_decomposition.py
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from agentproof.graph.model import graph_from_dict  # noqa: E402
from agentproof.verify import run_structural_checks  # noqa: E402
from risk_aware_gate import SENSITIVE_KEYWORDS  # noqa: E402
from slugkey import ambiguous_slugs  # noqa: E402

RW = ROOT / "corpus" / "real_world"
SELF_REPO_PREFIX = "NordicAgents__AgentProof"

STRUCTURAL_CHECKS = {
    "exit_reachability", "reverse_reachability", "dead_ends",
    "router_shape", "tool_declarations",
}
POLICY_CHECKS = {"human_presence", "human_gate_coverage"}

CHECK_ALIAS = {
    "router-non-conditional-edges": "router_shape",
    "sensitive-path-bypasses-human-review": "human_gate_coverage",
}


def wilson_ci(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 100.0]
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(100 * max(0.0, centre - half), 1),
            round(100 * min(1.0, centre + half), 1)]


def dist(labels: list[str], n: int) -> dict:
    if n == 0:
        return {}
    return {
        k: {"n": v, "pct": round(100 * v / n, 1), "wilson95": wilson_ci(v, n)}
        for k, v in sorted(Counter(labels).items(), key=lambda kv: -kv[1])
    }


def sensitive_tool_set(graphs) -> set[str]:
    keywords = [kw for kws in SENSITIVE_KEYWORDS.values() for kw in kws]
    out: set[str] = set()
    for g in graphs:
        for n in g.get("nodes", []):
            for t in n.get("tools", []) or []:
                if any(kw in t.lower() for kw in keywords):
                    out.add(t)
    return out


def failing_checks(graph: dict, sensitive: set[str]) -> set[str]:
    report = run_structural_checks(
        graph_from_dict(graph), require_human=True, sensitive_tools=sensitive)
    return {c["check_id"] for c in report["checks"] if not c["passed"]}


def has_human_node(graph: dict) -> bool:
    return any(n.get("kind") == "human" for n in graph.get("nodes", []))


def declares_sensitive_tool(graph: dict) -> list[str]:
    keywords = [kw for kws in SENSITIVE_KEYWORDS.values() for kw in kws]
    hits = []
    for n in graph.get("nodes", []):
        for t in n.get("tools", []) or []:
            if any(kw in t.lower() for kw in keywords):
                hits.append(t)
    return sorted(set(hits))


def _check_family(check: str) -> str:
    if check in STRUCTURAL_CHECKS:
        return "structural"
    if check in POLICY_CHECKS:
        return "human_gate"
    return "other"


def _summarize_false_positive_rows(rows: list[dict]) -> dict:
    """Summarize an arbitrary flag-row subset with unchanged estimands."""
    n_all = len(rows)
    non_act = [r for r in rows if r["cause"] != "ACTIONABLE"]

    by_check = defaultdict(list)
    by_fam = defaultdict(list)
    for row in non_act:
        by_check[row["check"]].append(row["cause"])
        by_fam[_check_family(row["check"])].append(row["cause"])

    return {
        "n_flags": n_all,
        "n_actionable": n_all - len(non_act),
        "n_non_actionable": len(non_act),
        "over_all_flags": dist([r["cause"] for r in rows], n_all),
        "over_non_actionable": dist(
            [r["cause"] for r in non_act], len(non_act)
        ),
        "by_check": {
            key: {"n": len(values), "dist": dist(values, len(values))}
            for key, values in sorted(
                by_check.items(), key=lambda item: -len(item[1])
            )
        },
        "by_check_family": {
            key: {"n": len(values), "dist": dist(values, len(values))}
            for key, values in sorted(
                by_fam.items(), key=lambda item: -len(item[1])
            )
        },
        "rule_counts": dict(Counter(row["rule"] for row in rows)),
        "rows": rows,
        "delta_vs_committed_mapping": _delta(rows),
    }


def _collision_exclusion(rows: list[dict], ambiguous: set[str]) -> dict:
    """Sensitivity analysis excluding non-unique legacy slug identities."""
    removed = [row for row in rows if row["slug"] in ambiguous]
    retained = [row for row in rows if row["slug"] not in ambiguous]
    affected_slugs = sorted({row["slug"] for row in removed})
    return {
        "rule": (
            "exclude every triage record whose legacy <repo>__<basename> "
            "slug maps to more than one distinct source path"
        ),
        "n_ambiguous_legacy_slugs_corpus": len(ambiguous),
        "n_ambiguous_legacy_slugs_in_triage": len(affected_slugs),
        "ambiguous_legacy_slugs_in_triage": affected_slugs,
        "n_flags_removed": len(removed),
        "removed_by_cause": dict(
            sorted(Counter(row["cause"] for row in removed).items())
        ),
        "removed_by_check_family": dict(
            sorted(Counter(_check_family(row["check"]) for row in removed).items())
        ),
        "retained": _summarize_false_positive_rows(retained),
    }


# ---------------------------------------------------------------------------


def decompose_false_positives(validated, gt_graphs, sensitive, fw,
                              gt_errors, non_discharging,
                              ambiguous_legacy_slugs: set[str] | None = None
                              ) -> dict:
    triage = [dict(t) for t in validated["triage_details"]
              if not t["slug"].startswith(SELF_REPO_PREFIX)]
    for t in triage:
        t["check"] = CHECK_ALIAS.get(t["check"], t["check"])

    # Cache the oracle-graph verdict once per slug.
    gt_fail: dict[str, set[str]] = {}
    for slug, g in gt_graphs.items():
        gt_fail[slug] = failing_checks(g, sensitive)

    rows = []
    for t in triage:
        slug, check, label = t["slug"], t["check"], t["label"]
        row = {"slug": slug, "check": check, "triage_label": label,
               "framework": fw.get(slug, "unknown")}

        if label == "real_defect":
            row.update(cause="ACTIONABLE", rule="R5")
        elif label == "arguable":
            row.update(cause="LABEL", rule="R4")
        else:
            gt = gt_fail.get(slug)
            gt_graph = gt_graphs.get(slug)
            # --- validity guard: is the reference graph trustworthy here? ---
            guard_a = (slug, check) in gt_errors
            guard_b = (check in POLICY_CHECKS and gt_graph is not None
                       and has_human_node(gt_graph)
                       and slug in non_discharging)
            if gt is None:
                # No reference graph: the survival test cannot be run.  Fall
                # back to the committed triage mapping and mark it.
                row.update(
                    cause="EXTRACTOR" if label == "extraction_artifact"
                    else "POLICY_SPEC",
                    rule="R0_no_reference_graph")
            elif guard_a:
                row.update(cause="REFERENCE_ERROR",
                           rule="Ga_gt_triage_marked_reference_wrong")
            elif guard_b:
                row.update(cause="REFERENCE_ERROR",
                           rule="Gb_reference_human_node_non_discharging")
            elif check not in gt:
                row.update(cause="EXTRACTOR", rule="R1_removed_by_oracle")
            elif check in STRUCTURAL_CHECKS:
                row.update(cause="CHECKER", rule="R2_structural_survives_oracle")
            elif check in POLICY_CHECKS:
                if has_human_node(gt_graph):
                    row.update(cause="CHECKER",
                               rule="R3b_gate_present_in_oracle")
                else:
                    row.update(cause="POLICY_SPEC",
                               rule="R3a_policy_survives_oracle")
            else:
                row.update(cause="POLICY_SPEC", rule="R3a_unclassified_check")
        rows.append(row)

    summary = _summarize_false_positive_rows(rows)
    summary["collision_exclusion"] = _collision_exclusion(
        rows, ambiguous_legacy_slugs or set()
    )
    return summary


def _delta(rows) -> dict:
    """How the survival test differs from the label->cause mapping it replaces."""
    old_map = {"extraction_artifact": "EXTRACTOR", "intentional": "POLICY_SPEC",
               "arguable": "LABEL", "real_defect": "ACTIONABLE"}
    moved = defaultdict(int)
    for r in rows:
        old = old_map[r["triage_label"]]
        if old != r["cause"]:
            moved[f"{old}->{r['cause']}"] += 1
    return {"n_reattributed": sum(moved.values()), "moves": dict(moved)}


def decompose_false_negatives(audit, v1_graphs, gt_graphs, gt_errors) -> dict:
    non_discharging = {p["slug"]: p["gate"]
                       for p in audit["placebo_and_ineffective_gates"]}
    violations = [v for v in audit["verdicts"] if v["verdict"] == "violation"]

    rows = []
    for v in violations:
        slug = v["slug"]
        g1 = v1_graphs.get(slug)
        gt = gt_graphs.get(slug)
        declared = declares_sensitive_tool(g1) if g1 else []
        row = {"slug": slug, "framework": v["framework"],
               "category": v["category"],
               "v1_graph_present": g1 is not None,
               "v1_declared_sensitive_tools": declared,
               "gt_has_human_node": has_human_node(gt) if gt else None,
               "non_discharging_gate": non_discharging.get(slug),
               "outside_both_flag_universes":
                   v.get("outside_both_flag_universes", False)}
        if not declared:
            row.update(cause="EXTRACTOR", rule="F1_no_sensitive_declaration")
        elif slug in non_discharging:
            row.update(cause="CHECKER", rule="F2_non_discharging_gate_accepted")
        else:
            row.update(cause="POLICY_SPEC", rule="F3_lexicon_gap")
        rows.append(row)

    causes = [r["cause"] for r in rows]

    # ---- Symmetric arm: replace the extractor with the reconstructed graph ----
    # This is the FN counterpart of the FP survival test.  Holding the policy
    # fixed and handing the check a higher-fidelity reconstructed graph, which
    # violations does
    # it STILL miss?  Those misses are the check-side false-negative floor.
    sens_gt = sensitive_tool_set(list(gt_graphs.values()))
    oracle = []
    for v in violations:
        slug = v["slug"]
        gt = gt_graphs.get(slug)
        if gt is None:
            oracle.append({"slug": slug, "cause": "NO_REFERENCE_GRAPH",
                           "rule": "G0"})
            continue
        fired = "human_gate_coverage" in failing_checks(gt, sens_gt)
        declared = declares_sensitive_tool(gt)
        row = {"slug": slug, "risk_aware_fires_on_oracle": fired,
               "gt_declared_sensitive_tools": declared,
               "gt_has_human_node": has_human_node(gt),
               "non_discharging_gate": non_discharging.get(slug)}
        if fired:
            row.update(cause="DETECTED", rule="G1_oracle_graph_detects")
        elif (slug, "tool_declarations") in gt_errors:
            # Same validity guard as the FP side: the GT triage recorded that
            # the reconstruction omitted tools the source declares statically,
            # so this miss is a reference-graph error, not an abstraction limit.
            row.update(cause="REFERENCE_ERROR",
                       rule="G2b_reference_omitted_declarable_tools")
        elif not declared:
            # No extractor could have fixed this within the node/edge/tool
            # vocabulary: the effect lives in a node BODY, which the graph
            # abstraction does not represent, extracted or reconstructed.
            row.update(cause="ABSTRACTION",
                       rule="G2_effect_absent_even_from_reference")
        elif slug in non_discharging:
            row.update(cause="CHECKER",
                       rule="G3_non_discharging_gate_accepted")
        else:
            row.update(cause="CHECKER", rule="G4_cleared_despite_violation")
        oracle.append(row)

    ocauses = [r["cause"] for r in oracle]
    n_still_missed = sum(1 for c in ocauses if c != "DETECTED")

    return {
        "n_source_audited_human_gate_violations": len(rows),
        "as_mined_pipeline": {
            "n_missed": len(rows),
            "dist": dist(causes, len(causes)) if rows else {},
            "rows": rows,
            "note": ("All 12 HGP-1 violations were missed by the as-mined "
                     "risk-aware pipeline (it fires 0 times on the 922 mined "
                     "graphs), so the miss denominator is the full violation "
                     "set."),
        },
        "reconstructed_reference_pipeline": {
            "n_detected": len(oracle) - n_still_missed,
            "n_still_missed": n_still_missed,
            "dist": dist(ocauses, len(ocauses)) if oracle else {},
            "rows": oracle,
            "note": ("Symmetric counterpart of the FP survival test: the "
                     "extractor is replaced by the source-reconstructed reference "
                     "graph and the policy is held fixed.  Violations still "
                     "missed are the check-side false-negative floor."),
        },
    }


def main() -> None:
    validated = json.loads((RW / "validated_results.json").read_text())
    audit = json.loads((RW / "human_gate_audit.json").read_text())

    gt_graphs = {p.stem: json.loads(p.read_text())
                 for p in sorted((RW / "ground_truth").glob("*.json"))
                 if not p.stem.startswith(SELF_REPO_PREFIX)}
    v1_graphs = {p.stem: json.loads(p.read_text())
                 for p in sorted((RW / "graphs").glob("*.json"))}

    fw = {s: g.get("framework") for s, g in v1_graphs.items()}
    for s, g in gt_graphs.items():
        fw.setdefault(s, g.get("framework"))

    sensitive = sensitive_tool_set(list(gt_graphs.values()))

    # Validity-guard inputs (see module docstring).
    gt_triage = json.loads((RW / "gt_triage_results.json").read_text())
    gt_errors = {
        (t["slug"], CHECK_ALIAS.get(t["check_id"], t["check_id"]))
        for t in gt_triage["triage"]
        if t.get("verify", {}).get("final_label",
                                   t["primary"]["label"]) == "gt_error"
    }
    non_discharging = {p["slug"]
                       for p in audit["placebo_and_ineffective_gates"]}
    mining_records = []
    for name in ("metadata.json", "metadata.lg_crew.json"):
        path = RW / name
        if path.exists():
            mining_records.extend(json.loads(path.read_text())["records"])
    ambiguous_legacy = set(ambiguous_slugs(mining_records))

    out = {
        "_meta": {
            "script": "scripts/fp_fn_decomposition.py",
            "purpose": ("separate CHECKER from POLICY_SPEC via a mechanical "
                        "oracle-survival test, and decompose false negatives "
                        "symmetrically"),
            "inputs": ["validated_results.json", "human_gate_audit.json",
                       "graphs/", "ground_truth/"],
            "fp_rules": {
                "R1": "check does not fire on the reference graph -> EXTRACTOR",
                "R2": "structural check still fires on the reference graph -> CHECKER",
                "R3a": "policy check still fires, no human node in reference -> POLICY_SPEC",
                "R3b": "policy check still fires but reference has a human node -> CHECKER",
                "R4": "arguable -> LABEL",
                "R5": "real_defect -> ACTIONABLE",
                "Ga": "GT triage marked the reference graph wrong here -> REFERENCE_ERROR",
                "Gb": "reference `human` node is non-discharging (placebo audit) -> REFERENCE_ERROR",
            },
            "fn_rules": {
                "F1": "no sensitive tool declared in the mined graph -> EXTRACTOR",
                "F2": "sensitive tool declared, non-discharging gate accepted -> CHECKER",
                "F3": "sensitive tool declared, no gate excuse -> POLICY_SPEC",
                "G1": "risk-aware check fires on the reference graph -> DETECTED",
                "G2": "effect absent even from the reference graph -> ABSTRACTION",
                "G3/G4": "reference graph shows the effect, check still clears -> CHECKER",
            },
            "guard_inputs": {
                "n_gt_error_flags": len(gt_errors),
                "n_non_discharging_gates": len(non_discharging),
            },
            "collision_input": {
                "metadata_files": ["metadata.json", "metadata.lg_crew.json"],
                "n_ambiguous_legacy_slugs": len(ambiguous_legacy),
            },
            "sensitive_tool_lexicon_hits": sorted(sensitive),
        },
        "false_positives": decompose_false_positives(
            validated, gt_graphs, sensitive, fw, gt_errors, non_discharging,
            ambiguous_legacy),
        "false_negatives": decompose_false_negatives(
            audit, v1_graphs, gt_graphs, gt_errors),
    }

    dest = RW / "fp_fn_decomposition.json"
    dest.write_text(json.dumps(out, indent=2) + "\n")

    fp = out["false_positives"]
    fn = out["false_negatives"]
    print(f"wrote {dest.relative_to(ROOT)}")
    print(f"\nFALSE POSITIVES  ({fp['n_flags']} flags, "
          f"{fp['n_non_actionable']} non-actionable)")
    for k, v in fp["over_non_actionable"].items():
        print(f"  {k:12s} {v['n']:4d}  {v['pct']:5.1f}%  {v['wilson95']}")
    print(f"  re-attributed vs committed mapping: "
          f"{fp['delta_vs_committed_mapping']['n_reattributed']} "
          f"{fp['delta_vs_committed_mapping']['moves']}")
    print("\n  by check family:")
    for fam, v in fp["by_check_family"].items():
        inner = "  ".join(f"{c}={d['n']}({d['pct']}%)"
                          for c, d in v["dist"].items())
        print(f"    {fam:12s} n={v['n']:3d}  {inner}")
    collision = fp["collision_exclusion"]
    retained = collision["retained"]
    print(
        "\n  collision exclusion: "
        f"{collision['n_ambiguous_legacy_slugs_in_triage']} slugs / "
        f"{collision['n_flags_removed']} flags removed; "
        f"{retained['n_flags']} flags retained"
    )
    for fam, v in retained["by_check_family"].items():
        inner = "  ".join(
            f"{cause}={details['n']}({details['pct']}%)"
            for cause, details in v["dist"].items()
        )
        print(f"    {fam:12s} n={v['n']:3d}  {inner}")
    print(f"\nFALSE NEGATIVES  ({fn['n_source_audited_human_gate_violations']} "
          f"source-audited violations)")
    print("  as-mined pipeline (v1 graph):")
    for k, v in fn["as_mined_pipeline"]["dist"].items():
        print(f"    {k:12s} {v['n']:4d}  {v['pct']:5.1f}%  {v['wilson95']}")
    og = fn["reconstructed_reference_pipeline"]
    print(f"  reconstructed reference, policy fixed: detected {og['n_detected']}, "
          f"still missed {og['n_still_missed']}")
    for k, v in og["dist"].items():
        print(f"    {k:12s} {v['n']:4d}  {v['pct']:5.1f}%  {v['wilson95']}")


if __name__ == "__main__":
    main()
