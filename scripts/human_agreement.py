#!/usr/bin/env python3
"""Score the two-annotator human validation once the worksheets are filled in.

This is the analysis half of the validation the paper lists as its principal
open gap.  The labelling half is done by hand in:

    corpus/annotations/worksheet_task1_reconstruction_{A,B}.json   (graphs)
    corpus/annotations/worksheet_task2_defects_{A,B}.json          (defects)

Run this at any point; it reports progress and scores whatever is complete, so
it is useful mid-way through annotation, not only at the end.

    uv run python scripts/human_agreement.py
    uv run python scripts/human_agreement.py --latex   # emit the .tex snippet

WHAT IT COMPUTES
----------------
Task 2 (defect labels), the estimand the paper's triage rests on:
  * raw pairwise agreement, Cohen's kappa, Krippendorff's alpha (nominal),
    each with two 95% bootstrap intervals: resampled over ITEMS, and --- the
    pre-registered primary for pooled statistics, per annotation guide v1.0
    section 8.4 --- resampled over REPOSITORY CLUSTERS, since workflows from
    one repository are not independent;
  * the same three statistics for each human against the committed LLM triage
    label.  This is the number that decides the paper's validity claim: if
    human-vs-LLM agreement is comparable to human-vs-human, the LLM labels are
    behaving like a third annotator rather than like a different instrument.

Task 1 (graph reconstruction), the estimand the fidelity table rests on:
  * human-vs-human node/edge F1 and node-kind agreement -- the ceiling any
    automatic extractor could be scored against;
  * human-vs-LLM-reference the same way, scored with the SAME matcher the
    fidelity study uses, so the numbers are directly comparable to Table 1.

Outputs corpus/annotations/human_agreement.json and, with --latex,
papers/paper1/generated/human_agreement.tex.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANN = ROOT / "corpus" / "annotations"
RW = ROOT / "corpus" / "real_world"
GEN = ROOT / "papers" / "paper1" / "generated"

N_BOOT = 10_000
SEED = 20260722

# The label domain the annotation guide fixes for task 2.
DEFECT_LABELS = ["real_defect", "extraction_artifact", "intentional", "arguable"]


# --------------------------------------------------------------------------
# agreement statistics
# --------------------------------------------------------------------------

def raw_agreement(pairs: list[tuple[str, str]]) -> float:
    if not pairs:
        return float("nan")
    return sum(1 for a, b in pairs if a == b) / len(pairs)


def cohens_kappa(pairs: list[tuple[str, str]]) -> float:
    """Cohen's kappa for two coders on nominal labels."""
    n = len(pairs)
    if n == 0:
        return float("nan")
    po = raw_agreement(pairs)
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum((ca[k] / n) * (cb[k] / n) for k in set(ca) | set(cb))
    if pe == 1.0:
        # Degenerate: both coders used a single identical label throughout.
        return float("nan")
    return (po - pe) / (1 - pe)


def krippendorff_alpha(pairs: list[tuple[str, str]]) -> float:
    """Krippendorff's alpha, nominal metric, two coders, no missing data.

    With exactly two coders per item this reduces to
        alpha = 1 - (n_units * D_o) / D_e
    computed from the coincidence matrix; we build it directly.
    """
    units = [list(p) for p in pairs]
    if not units:
        return float("nan")
    # Coincidence matrix over the observed label set.
    labels = sorted({v for u in units for v in u})
    idx = {l: i for i, l in enumerate(labels)}
    k = len(labels)
    coinc = [[0.0] * k for _ in range(k)]
    for u in units:
        m = len(u)  # 2
        if m < 2:
            continue
        for i in range(m):
            for j in range(m):
                if i != j:
                    coinc[idx[u[i]]][idx[u[j]]] += 1.0 / (m - 1)
    n_total = sum(sum(row) for row in coinc)
    if n_total == 0:
        return float("nan")
    marg = [sum(row) for row in coinc]
    # Nominal metric: disagreement is 1 off the diagonal, 0 on it.
    do = sum(coinc[i][j] for i in range(k) for j in range(k) if i != j)
    de = sum(marg[i] * marg[j] for i in range(k) for j in range(k) if i != j)
    de /= (n_total - 1)
    if de == 0:
        return float("nan")
    return 1 - do / de


def boot_ci(pairs: list[tuple[str, str]], fn, n_boot: int = N_BOOT) -> list[float]:
    """Percentile bootstrap over items."""
    if len(pairs) < 2:
        return [float("nan"), float("nan")]
    rng = random.Random(SEED)
    vals = []
    n = len(pairs)
    for _ in range(n_boot):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        v = fn(sample)
        if not math.isnan(v):
            vals.append(v)
    return _pct(vals)


def cluster_boot_ci(pairs: list[tuple[str, str]], clusters: list[str], fn,
                    n_boot: int = N_BOOT) -> list[float]:
    """Percentile bootstrap resampling CLUSTERS (repositories), not items.

    The annotation guide (v1.0, section 8.4) fixes this in advance for pooled
    statistics: workflows from one repository are not independent, so an
    item-level bootstrap understates the interval.
    """
    if len(pairs) < 2 or len(pairs) != len(clusters):
        return [float("nan"), float("nan")]
    by_cluster: dict[str, list[tuple[str, str]]] = {}
    for p, c in zip(pairs, clusters):
        by_cluster.setdefault(c, []).append(p)
    keys = sorted(by_cluster)
    if len(keys) < 2:
        return [float("nan"), float("nan")]
    rng = random.Random(SEED)
    vals = []
    for _ in range(n_boot):
        sample: list[tuple[str, str]] = []
        for _ in range(len(keys)):
            sample.extend(by_cluster[keys[rng.randrange(len(keys))]])
        v = fn(sample)
        if not math.isnan(v):
            vals.append(v)
    return _pct(vals)


def _pct(vals: list[float]) -> list[float]:
    if not vals:
        return [float("nan"), float("nan")]
    vals.sort()
    return [round(vals[int(0.025 * len(vals))], 3),
            round(vals[int(0.975 * len(vals)) - 1], 3)]


def repo_of(workflow_id: str) -> str:
    """`owner__repo__file` -> `owner/repo` (the clustering unit)."""
    parts = workflow_id.split("__")
    return "/".join(parts[:2]) if len(parts) >= 2 else workflow_id


def score_pairs(pairs: list[tuple[str, str]],
                clusters: list[str] | None = None) -> dict:
    def val(fn):
        if not pairs:
            return None
        v = fn(pairs)
        return None if math.isnan(v) else round(v, 3)

    out = {
        "n": len(pairs),
        "n_clusters": len(set(clusters)) if clusters else None,
        "raw_agreement": val(raw_agreement),
        "raw_agreement_ci": boot_ci(pairs, raw_agreement),
        "cohens_kappa": val(cohens_kappa),
        "cohens_kappa_ci": boot_ci(pairs, cohens_kappa),
        "krippendorff_alpha": val(krippendorff_alpha),
        "krippendorff_alpha_ci": boot_ci(pairs, krippendorff_alpha),
        "confusion": {f"{a}|{b}": c
                      for (a, b), c in sorted(Counter(pairs).items())},
    }
    if clusters:
        # Primary interval per the frozen protocol; the item-level ones above
        # are retained as the (narrower) secondary.
        out["cluster_bootstrap"] = {
            "_note": ("resamples repositories, not items; this is the "
                      "pre-registered primary interval for pooled statistics "
                      "(annotation guide v1.0 section 8.4)"),
            "raw_agreement_ci": cluster_boot_ci(pairs, clusters, raw_agreement),
            "cohens_kappa_ci": cluster_boot_ci(pairs, clusters, cohens_kappa),
            "krippendorff_alpha_ci": cluster_boot_ci(pairs, clusters,
                                                     krippendorff_alpha),
        }
    return out


# --------------------------------------------------------------------------
# graph comparison (same matcher shape as the fidelity study)
# --------------------------------------------------------------------------

def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if (tp + fp) else None
    r = tp / (tp + fn) if (tp + fn) else None
    f = (2 * p * r / (p + r)) if (p and r) else None
    return {"precision": round(p, 3) if p is not None else None,
            "recall": round(r, 3) if r is not None else None,
            "f1": round(f, 3) if f is not None else None,
            "tp": tp, "fp": fp, "fn": fn}


def compare_graphs(a: dict, b: dict) -> dict:
    """Score graph `a` against graph `b` treated as reference."""
    an = {n["id"] for n in a.get("nodes", [])}
    bn = {n["id"] for n in b.get("nodes", [])}
    ae = {(e["source"], e["target"]) for e in a.get("edges", [])}
    be = {(e["source"], e["target"]) for e in b.get("edges", [])}
    akind = {n["id"]: n.get("kind") for n in a.get("nodes", [])}
    bkind = {n["id"]: n.get("kind") for n in b.get("nodes", [])}
    shared = an & bn
    kind_hits = sum(1 for i in shared if akind.get(i) == bkind.get(i))
    return {
        "nodes": prf(len(an & bn), len(an - bn), len(bn - an)),
        "edges": prf(len(ae & be), len(ae - be), len(be - ae)),
        "kind_accuracy": (round(kind_hits / len(shared), 3) if shared else None),
        "n_shared_nodes": len(shared),
    }


def mean_of(rows: list[dict], *path) -> float | None:
    vals = []
    for r in rows:
        v = r
        for p in path:
            v = (v or {}).get(p) if isinstance(v, dict) else None
        if isinstance(v, (int, float)):
            vals.append(v)
    return round(sum(vals) / len(vals), 3) if vals else None


# --------------------------------------------------------------------------

def load(name: str) -> dict | None:
    p = ANN / name
    return json.loads(p.read_text()) if p.exists() else None


def committed_llm_labels() -> dict[tuple[str, str], str]:
    """(workflow_id, check_id) -> final LLM triage label."""
    out: dict[tuple[str, str], str] = {}
    combined = json.loads((RW / "wf_output_combined.json").read_text())
    for t in combined["triage"]:
        for lab in t.get("labels", []):
            key = (t["slug"], lab.get("check_id"))
            out[key] = lab.get("final_label") or lab.get("label")
    return out


def score_task2(llm: dict) -> dict:
    a, b = load("worksheet_task2_defects_A.json"), load(
        "worksheet_task2_defects_B.json")
    if not a or not b:
        return {"status": "worksheets_missing"}

    ai = {(i["workflow_id"], i["check_id"]): i for i in a["flag_items"]}
    bi = {(i["workflow_id"], i["check_id"]): i for i in b["flag_items"]}
    keys = sorted(set(ai) & set(bi))

    done = [k for k in keys if ai[k].get("label") and bi[k].get("label")]
    hh = [(ai[k]["label"], bi[k]["label"]) for k in done]
    hh_cl = [repo_of(k[0]) for k in done]
    ha = [(ai[k]["label"], llm[k]) for k in done if k in llm]
    ha_cl = [repo_of(k[0]) for k in done if k in llm]
    hb = [(bi[k]["label"], llm[k]) for k in done if k in llm]

    # No-flag sweep: did either human find a defect the checker never flagged?
    nf_a = {i["workflow_id"]: i for i in a.get("no_flag_items", [])}
    nf_b = {i["workflow_id"]: i for i in b.get("no_flag_items", [])}
    nf_keys = sorted(set(nf_a) & set(nf_b))
    nf_done = [k for k in nf_keys
               if nf_a[k].get("verdict") and nf_b[k].get("verdict")]
    nf_pairs = [(nf_a[k]["verdict"], nf_b[k]["verdict"]) for k in nf_done]
    nf_cl = [repo_of(k) for k in nf_done]
    nf_found = sorted({k for k in nf_done
                       if "defect" in (nf_a[k]["verdict"] + nf_b[k]["verdict"])})

    return {
        "status": "complete" if len(done) == len(keys) else "partial",
        "n_flag_items": len(keys),
        "n_flag_items_labelled_by_both": len(done),
        "human_vs_human": score_pairs(hh, hh_cl),
        "human_A_vs_llm": score_pairs(ha, ha_cl),
        "human_B_vs_llm": score_pairs(hb, ha_cl),
        "no_flag_sweep": {
            "n_items": len(nf_keys),
            "n_completed_by_both": len(nf_done),
            "human_vs_human": score_pairs(nf_pairs, nf_cl),
            "workflows_where_a_human_found_an_unflagged_defect": nf_found,
            "note": ("A non-empty list here is a FALSE-NEGATIVE finding: a "
                     "defect outside the flag universe entirely, which flag "
                     "triage cannot see by construction."),
        },
        "interpretation": (
            "The decisive comparison is human_vs_human against human_*_vs_llm. "
            "If the LLM agrees with each human about as well as the humans "
            "agree with each other, the LLM labels are a third annotator. If "
            "human_vs_human is materially higher, the LLM is a different "
            "instrument and every LLM-derived prevalence figure inherits that "
            "gap."),
    }


def score_task1() -> dict:
    a, b = load("worksheet_task1_reconstruction_A.json"), load(
        "worksheet_task1_reconstruction_B.json")
    if not a or not b:
        return {"status": "worksheets_missing"}

    ai = {i["workflow_id"]: i for i in a["items"]}
    bi = {i["workflow_id"]: i for i in b["items"]}
    keys = sorted(set(ai) & set(bi))

    def filled(item) -> bool:
        r = item.get("reconstruction") or {}
        return bool(r.get("nodes")) and not item.get("insufficient_evidence")

    done = [k for k in keys if filled(ai[k]) and filled(bi[k])]

    hh, hg_a, hg_b = [], [], []
    for k in done:
        ga, gb = ai[k]["reconstruction"], bi[k]["reconstruction"]
        hh.append(compare_graphs(ga, gb))
        ref_p = RW / "ground_truth" / f"{k}.json"
        if ref_p.exists():
            ref = json.loads(ref_p.read_text())
            hg_a.append(compare_graphs(ga, ref))
            hg_b.append(compare_graphs(gb, ref))

    def agg(rows, label):
        return {
            "n": len(rows),
            "mean_node_f1": mean_of(rows, "nodes", "f1"),
            "mean_edge_f1": mean_of(rows, "edges", "f1"),
            "mean_edge_recall": mean_of(rows, "edges", "recall"),
            "mean_kind_accuracy": mean_of(rows, "kind_accuracy"),
            "_scored_against": label,
        }

    return {
        "status": "complete" if len(done) == len(keys) else "partial",
        "n_items": len(keys),
        "n_reconstructed_by_both": len(done),
        "n_insufficient_evidence": sum(
            1 for k in keys
            if ai[k].get("insufficient_evidence")
            or bi[k].get("insufficient_evidence")),
        "human_vs_human": agg(hh, "annotator B"),
        "human_A_vs_llm_reference": agg(hg_a, "LLM reference graph"),
        "human_B_vs_llm_reference": agg(hg_b, "LLM reference graph"),
        "interpretation": (
            "human_vs_human is the ceiling: no automatic extractor should be "
            "credited with fidelity above the level at which two humans agree "
            "on what the graph even is. Compare Table 1's edge recall against "
            "mean_edge_f1 here before reading the fidelity numbers as absolute."),
    }


def emit_latex(out: dict) -> str:
    t1, t2 = out["task1_graph_reconstruction"], out["task2_defect_labels"]
    if t2.get("status") == "worksheets_missing":
        return "% human validation not yet run\n"

    def g(d, *p, default="--"):
        v = d
        for k in p:
            v = (v or {}).get(k) if isinstance(v, dict) else None
        return v if v is not None else default

    return f"""% Generated by scripts/human_agreement.py -- do not edit by hand.
\\newcommand{{\\humanNflags}}{{{g(t2, 'n_flag_items_labelled_by_both')}}}
\\newcommand{{\\humanKappa}}{{{g(t2, 'human_vs_human', 'cohens_kappa')}}}
\\newcommand{{\\humanAlpha}}{{{g(t2, 'human_vs_human', 'krippendorff_alpha')}}}
\\newcommand{{\\humanRaw}}{{{g(t2, 'human_vs_human', 'raw_agreement')}}}
\\newcommand{{\\humanLLMkappaA}}{{{g(t2, 'human_A_vs_llm', 'cohens_kappa')}}}
\\newcommand{{\\humanLLMkappaB}}{{{g(t2, 'human_B_vs_llm', 'cohens_kappa')}}}
\\newcommand{{\\humanGraphN}}{{{g(t1, 'n_reconstructed_by_both')}}}
\\newcommand{{\\humanGraphEdgeF}}{{{g(t1, 'human_vs_human', 'mean_edge_f1')}}}
\\newcommand{{\\humanGraphKind}}{{{g(t1, 'human_vs_human', 'mean_kind_accuracy')}}}
\\newcommand{{\\humanRefEdgeF}}{{{g(t1, 'human_A_vs_llm_reference', 'mean_edge_f1')}}}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--latex", action="store_true",
                    help="also write the .tex macro file")
    args = ap.parse_args()

    llm = committed_llm_labels()
    out = {
        "_meta": {
            "script": "scripts/human_agreement.py",
            "n_bootstrap": N_BOOT,
            "seed": SEED,
            "label_domain_task2": DEFECT_LABELS,
            "purpose": ("score the two-annotator human validation and compare "
                        "it against the committed LLM labels"),
        },
        "task1_graph_reconstruction": score_task1(),
        "task2_defect_labels": score_task2(llm),
    }

    dest = ANN / "human_agreement.json"
    dest.write_text(json.dumps(out, indent=2) + "\n")
    print(f"wrote {dest.relative_to(ROOT)}")

    for name, sec in (("Task 1 (graph reconstruction)",
                       out["task1_graph_reconstruction"]),
                      ("Task 2 (defect labels)", out["task2_defect_labels"])):
        print(f"\n{name}: {sec.get('status')}")
        if sec.get("status") == "worksheets_missing":
            print("  worksheets not found under corpus/annotations/")
            continue
        if "n_flag_items_labelled_by_both" in sec:
            print(f"  labelled by both: "
                  f"{sec['n_flag_items_labelled_by_both']}/{sec['n_flag_items']}")
            hh = sec["human_vs_human"]
            print(f"  human-human : raw={hh['raw_agreement']} "
                  f"kappa={hh['cohens_kappa']} {hh['cohens_kappa_ci']} "
                  f"alpha={hh['krippendorff_alpha']}")
            for k in ("human_A_vs_llm", "human_B_vs_llm"):
                s = sec[k]
                print(f"  {k:16s}: raw={s['raw_agreement']} "
                      f"kappa={s['cohens_kappa']} {s['cohens_kappa_ci']}")
            nf = sec["no_flag_sweep"]
            print(f"  no-flag sweep: {nf['n_completed_by_both']}/{nf['n_items']} "
                  f"done, unflagged defects found: "
                  f"{len(nf['workflows_where_a_human_found_an_unflagged_defect'])}")
        else:
            print(f"  reconstructed by both: "
                  f"{sec['n_reconstructed_by_both']}/{sec['n_items']}")
            hh = sec["human_vs_human"]
            print(f"  human-human : node F1={hh['mean_node_f1']} "
                  f"edge F1={hh['mean_edge_f1']} kind={hh['mean_kind_accuracy']}")
            ra = sec["human_A_vs_llm_reference"]
            print(f"  A vs LLM ref: node F1={ra['mean_node_f1']} "
                  f"edge F1={ra['mean_edge_f1']} kind={ra['mean_kind_accuracy']}")

    if args.latex:
        GEN.mkdir(parents=True, exist_ok=True)
        p = GEN / "human_agreement.tex"
        p.write_text(emit_latex(out))
        print(f"\nwrote {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
