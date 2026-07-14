#!/usr/bin/env python3
"""Deterministic sampler for the two-human annotation study (plan section 3.3).

Emits ``corpus/annotations/samples_manifest.json`` with three lists:

(a) ``reconstruction_sample``  — 32 workflows, stratified 8 per framework and,
    within each framework, balanced 4/4 between *application-like* and
    *tutorial/demo/test* source classifications. The classification comes from
    the source-level census in ``corpus/real_world/gt_triage_results.json``
    (``classification``), which exists only for the 119-workflow validated
    sample; the reconstruction sample is therefore drawn from that sample
    (which is also what lets human reconstructions be compared 1:1 against the
    LLM ground-truth graphs and the AST extractor). If a stratum has fewer
    than 4 candidates, the shortfall is filled from the other stratum of the
    same framework and the gap is recorded in the manifest.

(b) ``defect_label_sample``    — every flag raised on the reconstructed
    ground-truth graphs (``gt_flags_for_triage.json``, 16 flags) plus every
    claimed genuine defect from the extracted-graph triage
    (``validated_results.json`` triage_details with label ``real_defect``).
    Items are (workflow, check) pairs; the four claimed genuine defects are
    marked ``claimed_genuine: true``.

(c) ``no_flag_sample``         — a repository-stratified random sample of >=30
    workflows (default 32) from the full mined corpus on which the instrument
    raised NO defect-relevant flag, for the false-negative audit. "No flag"
    means: none of the five structural checks (exit_reachability,
    reverse_reachability, dead_ends, router_shape, tool_declarations) nor the
    risk-aware human_gate_coverage check fired on the extracted graph, and the
    workflow carries no flag on its reconstructed graph either. The blunt
    human_presence check is deliberately NOT counted as a flag here: it fires
    on 91% of the mined corpus, so excluding its firings would reduce the
    audit pool to a heavily skewed 9% remnant; this decision is recorded in
    the manifest. At most one workflow per repository is drawn, with slots
    allocated across frameworks proportionally to each framework's number of
    eligible repositories.

Also emits blank per-annotator worksheets for Task 1 and Task 2 next to the
manifest, so the protocol in corpus/annotations/ANNOTATION_GUIDE.md is
immediately executable.

Determinism: a fixed seed (default 20260713, override with ``--seed``), all
candidate lists sorted before sampling, no timestamps in the output.

Usage:
    python scripts/make_annotation_samples.py [--seed N] [--noflag-n N]
        [--output corpus/annotations/samples_manifest.json] [--no-worksheets]
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RW = ROOT / "corpus" / "real_world"
ANNOT_DIR = ROOT / "corpus" / "annotations"

STRUCTURAL_CHECKS = {
    "exit_reachability",
    "reverse_reachability",
    "dead_ends",
    "router_shape",
    "tool_declarations",
}
# Checks that count as "flags" for the false-negative (no-flag) audit.
# human_presence is intentionally excluded; see module docstring.
FLAG_CHECKS = STRUCTURAL_CHECKS | {"human_gate_coverage"}

# Merge the census categories into the two strata the plan asks to balance.
APPLICATION_CATEGORIES = {"application_like"}
TUTORIAL_CATEGORIES = {"tutorial_or_example", "demo_or_toy", "test"}

NAME_PAT = re.compile(
    r"(test|tutorial|example|demo|exercise|learn|course|sample|starter|"
    r"quickstart|playground|template|lesson)",
    re.I,
)

SELF_REPO_PREFIX = "NordicAgents__AgentProof"

PILOT_N = 5  # plan 3.2: pilot the protocol on 5 workflows first


def slug_repo(slug: str) -> str:
    parts = slug.split("__")
    return f"{parts[0]}/{parts[1]}" if len(parts) >= 2 else slug


def load_json(path: Path):
    with open(path) as f:
        return json.load(f)


def build_provenance_lut() -> dict[str, dict]:
    """slug -> {repo, file_path, sha, url, ...} from both metadata files."""
    lut: dict[str, dict] = {}
    for name in ("metadata.json", "metadata.lg_crew.json"):
        p = RW / name
        if not p.exists():
            continue
        for rec in load_json(p).get("records", []):
            slug = rec.get("slug")
            if slug and slug not in lut:
                lut[slug] = rec
    return lut


def provenance_entry(slug: str, lut: dict[str, dict], gaps: list[str]) -> dict:
    rec = lut.get(slug, {})
    repo = rec.get("repo") or slug_repo(slug)
    sha = rec.get("sha", "")
    file_path = rec.get("file_path", "")
    url = rec.get("url", "")
    if not url and repo and sha and file_path:
        url = f"https://github.com/{repo}/blob/{sha}/{file_path}"
        gaps.append(
            f"{slug}: no recorded url in metadata; synthesized from repo+sha+file_path"
        )
    gt_path = RW / "ground_truth" / f"{slug}.json"
    ex_path = RW / "graphs" / f"{slug}.json"
    return {
        "workflow_id": slug,
        "repository": repo,
        "source_path": file_path,
        "source_url": url,
        "commit_sha": sha,
        "extracted_graph_path": str(ex_path.relative_to(ROOT)) if ex_path.exists() else None,
        "ground_truth_graph_path": str(gt_path.relative_to(ROOT)) if gt_path.exists() else None,
    }


def make_reconstruction_sample(rng: random.Random, lut, gaps: list[str]) -> list[dict]:
    ra = load_json(RW / "revision_analyses.json")
    per_wf = {
        w["slug"]: w
        for w in ra["prevalence_gt"]["per_workflow"]
        if not w["slug"].startswith(SELF_REPO_PREFIX)
    }
    gtr = load_json(RW / "gt_triage_results.json")
    category = {c["slug"]: c["category"] for c in gtr["classification"]}

    # Bucket the validated sample by (framework, stratum).
    buckets: dict[tuple[str, str], list[str]] = defaultdict(list)
    for slug, w in per_wf.items():
        cat = category.get(slug)
        if cat is None:
            gaps.append(
                f"{slug}: in validated sample but missing source-level "
                "classification; excluded from reconstruction strata"
            )
            continue
        if cat in APPLICATION_CATEGORIES:
            stratum = "application_like"
        elif cat in TUTORIAL_CATEGORIES:
            stratum = "tutorial_demo_test"
        else:
            gaps.append(f"{slug}: unrecognized census category {cat!r}; excluded")
            continue
        buckets[(w["framework"], stratum)].append(slug)

    frameworks = sorted({fw for fw, _ in buckets})
    sample: list[dict] = []
    for fw in frameworks:
        picked_fw: list[tuple[str, str]] = []
        for stratum in ("application_like", "tutorial_demo_test"):
            cands = sorted(buckets.get((fw, stratum), []))
            take = min(4, len(cands))
            if take < 4:
                gaps.append(
                    f"stratum {fw}/{stratum}: only {len(cands)} candidates in the "
                    f"validated sample (wanted 4); shortfall filled from the "
                    f"other {fw} stratum"
                )
            picked_fw += [(s, stratum) for s in rng.sample(cands, take)]
        # Fill any shortfall from the other stratum of the same framework.
        while len(picked_fw) < 8:
            already = {s for s, _ in picked_fw}
            spare = sorted(
                (s, st)
                for st in ("application_like", "tutorial_demo_test")
                for s in buckets.get((fw, st), [])
                if s not in already
            )
            if not spare:
                gaps.append(
                    f"framework {fw}: fewer than 8 classified workflows available; "
                    f"sampled {len(picked_fw)}"
                )
                break
            picked_fw.append(spare[rng.randrange(len(spare))])
        for slug, stratum in picked_fw:
            entry = provenance_entry(slug, lut, gaps)
            entry.update(
                {
                    "framework": fw,
                    "stratum": f"{fw}/{stratum}",
                    "source_classification": category.get(slug),
                    "llm_gt_confidence": per_wf[slug].get("gt_confidence"),
                    "pilot": False,
                    "why_selected": (
                        f"Task 1 graph reconstruction: uniform random draw (seeded) "
                        f"from the {fw}/{stratum} stratum of the 119-workflow "
                        f"validated sample (plan 3.3: 8 per framework, balanced "
                        f"application-like vs tutorial/demo/test)."
                    ),
                }
            )
            sample.append(entry)

    # Deterministic pilot designation: one workflow per framework plus one
    # extra, chosen from the sample itself (plan 3.2: pilot on 5 workflows).
    sample.sort(key=lambda e: e["workflow_id"])
    pilot_picked: list[str] = []
    for fw in frameworks:
        fw_items = [e for e in sample if e["framework"] == fw]
        if fw_items:
            pilot_picked.append(rng.choice(fw_items)["workflow_id"])
    remaining = sorted(
        e["workflow_id"] for e in sample if e["workflow_id"] not in pilot_picked
    )
    while len(pilot_picked) < min(PILOT_N, len(sample)) and remaining:
        pilot_picked.append(remaining.pop(rng.randrange(len(remaining))))
    for e in sample:
        if e["workflow_id"] in pilot_picked:
            e["pilot"] = True
            e["why_selected"] += " Designated pilot workflow (plan 3.2)."
    return sample


def make_defect_label_sample(lut, gaps: list[str]) -> list[dict]:
    items: list[dict] = []

    # (b.1) Every flag raised on the reconstructed ground-truth graphs.
    gt_flags = load_json(RW / "gt_flags_for_triage.json")
    gtr = load_json(RW / "gt_triage_results.json")
    final_label: dict[tuple[str, str], str] = {}
    for t in gtr.get("triage", []):
        verify = t.get("verify") or {}
        lab = verify.get("final_label") or t.get("primary", {}).get("label")
        final_label[(t["slug"], t["check_id"])] = lab
    for fl in gt_flags:
        slug, check = fl["slug"], fl["check_id"]
        claimed = final_label.get((slug, check)) == "real_defect"
        entry = provenance_entry(slug, lut, gaps)
        entry.update(
            {
                "framework": fl.get("framework"),
                "check_id": check,
                "stratum": "gt_graph_flag",
                "claimed_genuine": claimed,
                "flag_detail": fl.get("detail"),
                "why_selected": (
                    "Task 2 defect labeling: flag raised when the checks were "
                    "re-run on the reconstructed ground-truth graph "
                    "(gt_flags_for_triage.json); plan 3.3 requires all such "
                    "flags to be independently reviewed."
                ),
            }
        )
        if claimed:
            entry["why_selected"] += (
                " Also one of the paper's claimed genuine defects "
                "(gt_triage_results.json final label real_defect)."
            )
        items.append(entry)

    # (b.2) Every claimed genuine defect from the extracted-graph triage.
    vr = load_json(RW / "validated_results.json")
    seen = {(i["workflow_id"], i["check_id"]) for i in items}
    for t in vr.get("triage_details", []):
        if t.get("label") != "real_defect":
            continue
        slug, check = t["slug"], t["check"]
        if (slug, check) in seen:
            continue
        entry = provenance_entry(slug, lut, gaps)
        entry.update(
            {
                "framework": (lut.get(slug) or {}).get("framework"),
                "check_id": check,
                "stratum": "extracted_flag_claimed_genuine",
                "claimed_genuine": True,
                "flag_detail": None,
                "why_selected": (
                    "Task 2 defect labeling: claimed genuine defect from the "
                    "adversarial triage of extracted-graph flags "
                    "(validated_results.json triage_details, label "
                    "real_defect); plan 3.3 requires every claimed genuine "
                    "defect to be independently reviewed."
                ),
            }
        )
        items.append(entry)

    items.sort(key=lambda e: (e["workflow_id"], e["check_id"]))
    return items


def make_no_flag_sample(
    rng: random.Random, lut, exclude_slugs: set[str], n_target: int, gaps: list[str]
) -> list[dict]:
    dr = load_json(RW / "defect_results.json")
    pool: list[str] = []
    for w in dr.get("details", []):
        slug = w["name"]
        if slug.startswith(SELF_REPO_PREFIX) or slug in exclude_slugs:
            continue
        fired = {c.get("check") for c in w.get("defects", [])}
        if fired & FLAG_CHECKS:
            continue
        pool.append(slug)
    pool.sort()

    # Group by repository (stratification unit), then by framework.
    by_repo: dict[str, list[str]] = defaultdict(list)
    for slug in pool:
        by_repo[slug_repo(slug)].append(slug)
    repo_fw: dict[str, str] = {}
    for repo, slugs in by_repo.items():
        fw = (lut.get(slugs[0]) or {}).get("framework", "unknown")
        repo_fw[repo] = fw
    fw_repos: dict[str, list[str]] = defaultdict(list)
    for repo in sorted(by_repo):
        fw_repos[repo_fw[repo]].append(repo)

    # Allocate slots proportionally to eligible repos per framework (>=1 each).
    total_repos = sum(len(v) for v in fw_repos.values())
    alloc: dict[str, int] = {}
    for fw in sorted(fw_repos):
        alloc[fw] = max(1, round(n_target * len(fw_repos[fw]) / total_repos))
    # Adjust rounding drift toward the largest strata.
    order = sorted(alloc, key=lambda f: -len(fw_repos[f]))
    i = 0
    while sum(alloc.values()) != n_target and order:
        fw = order[i % len(order)]
        if sum(alloc.values()) > n_target and alloc[fw] > 1:
            alloc[fw] -= 1
        elif sum(alloc.values()) < n_target and alloc[fw] < len(fw_repos[fw]):
            alloc[fw] += 1
        i += 1
        if i > 1000:  # safety
            break

    sample: list[dict] = []
    for fw in sorted(fw_repos):
        take = min(alloc.get(fw, 0), len(fw_repos[fw]))
        if take < alloc.get(fw, 0):
            gaps.append(
                f"no-flag stratum {fw}: only {len(fw_repos[fw])} eligible "
                f"repositories (wanted {alloc[fw]})"
            )
        for repo in rng.sample(sorted(fw_repos[fw]), take):
            slug = rng.choice(sorted(by_repo[repo]))
            entry = provenance_entry(slug, lut, gaps)
            entry.update(
                {
                    "framework": fw,
                    "stratum": f"no_flag/{fw}",
                    "tutorialish_filename": bool(NAME_PAT.search(slug.split("__", 2)[-1])),
                    "why_selected": (
                        "False-negative audit: no structural or "
                        "human_gate_coverage flag on the extracted graph, no "
                        "flag on any reconstructed graph, not a claimed "
                        "defect; one workflow drawn (seeded) per repository, "
                        f"repositories drawn from the {fw} stratum "
                        "proportionally to eligible-repo counts (plan 3.3: "
                        "repository-stratified random no-flag sample)."
                    ),
                }
            )
            sample.append(entry)
    sample.sort(key=lambda e: e["workflow_id"])
    return sample


def write_worksheets(manifest: dict) -> list[Path]:
    """Blank per-annotator worksheets so the protocol is directly executable."""
    written = []
    task1_items = [
        {
            "workflow_id": e["workflow_id"],
            "source_url": e["source_url"],
            "source_path": e["source_path"],
            "commit_sha": e["commit_sha"],
            "pilot": e["pilot"],
            "reconstruction": {
                "entry_id": "",
                "exit_ids": [],
                "nodes": [],
                "edges": [],
            },
            "insufficient_evidence": False,
            "insufficient_evidence_scope": [],
            "notes": "",
            "committed": False,
        }
        for e in manifest["reconstruction_sample"]
    ]
    flag_items = [
        {
            "workflow_id": e["workflow_id"],
            "check_id": e["check_id"],
            "source_url": e["source_url"],
            "source_path": e["source_path"],
            "commit_sha": e["commit_sha"],
            "label": "",
            "source_line_citations": [],
            "rationale": "",
            "committed": False,
        }
        for e in manifest["defect_label_sample"]
    ]
    noflag_items = [
        {
            "workflow_id": e["workflow_id"],
            "source_url": e["source_url"],
            "source_path": e["source_path"],
            "commit_sha": e["commit_sha"],
            "verdict": "",
            "defect_check_id": "",
            "source_line_citations": [],
            "rationale": "",
            "committed": False,
        }
        for e in manifest["no_flag_sample"]
    ]
    for annot in ("A", "B"):
        p1 = ANNOT_DIR / f"worksheet_task1_reconstruction_{annot}.json"
        p1.write_text(
            json.dumps(
                {"annotator": annot, "task": "graph_reconstruction", "items": task1_items},
                indent=2,
            )
            + "\n"
        )
        written.append(p1)
        p2 = ANNOT_DIR / f"worksheet_task2_defects_{annot}.json"
        p2.write_text(
            json.dumps(
                {
                    "annotator": annot,
                    "task": "defect_labeling",
                    "flag_items": flag_items,
                    "no_flag_items": noflag_items,
                },
                indent=2,
            )
            + "\n"
        )
        written.append(p2)
    return written


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seed", type=int, default=20260713)
    ap.add_argument(
        "--noflag-n",
        type=int,
        default=32,
        help="size of the no-flag false-negative sample (plan minimum: 30)",
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=ANNOT_DIR / "samples_manifest.json",
    )
    ap.add_argument("--no-worksheets", action="store_true")
    args = ap.parse_args()
    if args.noflag_n < 30:
        ap.error("--noflag-n must be >= 30 (plan section 3.3)")
    if args.output.is_dir():
        ap.error(
            f"--output expects the manifest FILE path to write "
            f"(e.g. corpus/annotations/samples_manifest.json), "
            f"but {args.output} is a directory"
        )

    rng = random.Random(args.seed)
    gaps: list[str] = [
        "No local source snapshots exist (corpus/real_world/sources/ is absent); "
        "annotators must read source at the pinned source_url "
        "(repository@commit_sha/file_path).",
        "Source-level application-like vs tutorial/demo/test classification "
        "exists only for the 119-workflow validated sample "
        "(gt_triage_results.json). The reconstruction sample is therefore "
        "drawn from that sample; for the no-flag sample only the filename "
        "heuristic (tutorialish_filename) is available, and no "
        "application-like balance is attempted there.",
        "The blunt human_presence check is not counted as a flag for the "
        "no-flag pool: it fires on 91% of the mined corpus, so excluding its "
        "firings would leave a small, skewed audit pool. Its firings are "
        "triaged separately in the paper's Task-2 data.",
    ]

    lut = build_provenance_lut()
    reconstruction = make_reconstruction_sample(rng, lut, gaps)
    defect_labels = make_defect_label_sample(lut, gaps)

    exclude = {e["workflow_id"] for e in defect_labels}
    # Also exclude any workflow whose reconstructed graph raised a flag
    # (they are already in the defect-label sample by construction).
    no_flag = make_no_flag_sample(rng, lut, exclude, args.noflag_n, gaps)

    manifest = {
        "generated_by": "scripts/make_annotation_samples.py",
        "seed": args.seed,
        "plan_reference": "papers/paper1/aaai/TOP_TIER_RESEARCH_PLAN.md section 3.3",
        "annotation_guide": "corpus/annotations/ANNOTATION_GUIDE.md",
        "inputs": [
            "corpus/real_world/revision_analyses.json",
            "corpus/real_world/gt_triage_results.json",
            "corpus/real_world/gt_flags_for_triage.json",
            "corpus/real_world/validated_results.json",
            "corpus/real_world/defect_results.json",
            "corpus/real_world/metadata.json",
            "corpus/real_world/metadata.lg_crew.json",
        ],
        "definitions": {
            "reconstruction_stratum": (
                "framework x (application_like | tutorial_demo_test), where "
                "tutorial_demo_test merges the census categories "
                "tutorial_or_example, demo_or_toy, and test"
            ),
            "no_flag": (
                "no exit_reachability / reverse_reachability / dead_ends / "
                "router_shape / tool_declarations / human_gate_coverage flag "
                "on the extracted graph, no flag on the reconstructed graph, "
                "and not a claimed genuine defect (human_presence excluded; "
                "see gaps)"
            ),
        },
        "gaps": gaps,
        "reconstruction_sample": reconstruction,
        "defect_label_sample": defect_labels,
        "no_flag_sample": no_flag,
        "summary": {
            "reconstruction_n": len(reconstruction),
            "reconstruction_by_stratum": {},
            "defect_label_n": len(defect_labels),
            "defect_label_claimed_genuine": sum(
                1 for e in defect_labels if e["claimed_genuine"]
            ),
            "no_flag_n": len(no_flag),
            "no_flag_by_framework": {},
        },
    }
    by_stratum: dict[str, int] = defaultdict(int)
    for e in reconstruction:
        by_stratum[e["stratum"]] += 1
    manifest["summary"]["reconstruction_by_stratum"] = dict(sorted(by_stratum.items()))
    by_fw: dict[str, int] = defaultdict(int)
    for e in no_flag:
        by_fw[e["framework"]] += 1
    manifest["summary"]["no_flag_by_framework"] = dict(sorted(by_fw.items()))

    ANNOT_DIR.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2) + "\n")

    worksheet_paths: list[Path] = []
    if not args.no_worksheets:
        worksheet_paths = write_worksheets(manifest)

    # ---- summary table ----
    print(f"wrote {args.output}  (seed={args.seed})")
    for p in worksheet_paths:
        print(f"wrote {p}")
    print()
    print(f"{'list':<24}{'stratum':<38}{'n':>4}")
    print("-" * 66)
    for stratum, n in sorted(by_stratum.items()):
        print(f"{'reconstruction':<24}{stratum:<38}{n:>4}")
    print(f"{'reconstruction':<24}{'TOTAL (pilot=' + str(sum(1 for e in reconstruction if e['pilot'])) + ')':<38}{len(reconstruction):>4}")
    n_gt = sum(1 for e in defect_labels if e["stratum"] == "gt_graph_flag")
    n_ex = len(defect_labels) - n_gt
    n_cg = manifest["summary"]["defect_label_claimed_genuine"]
    print(f"{'defect-label':<24}{'gt_graph_flag':<38}{n_gt:>4}")
    print(f"{'defect-label':<24}{'extracted_flag_claimed_genuine':<38}{n_ex:>4}")
    print(f"{'defect-label':<24}{'TOTAL (claimed_genuine=' + str(n_cg) + ')':<38}{len(defect_labels):>4}")
    for fw, n in sorted(by_fw.items()):
        print(f"{'no-flag audit':<24}{'no_flag/' + fw:<38}{n:>4}")
    print(f"{'no-flag audit':<24}{'TOTAL':<38}{len(no_flag):>4}")
    if gaps:
        print("\ngaps recorded in manifest:")
        for g in gaps:
            print(f"  - {g.splitlines()[0][:100]}")


if __name__ == "__main__":
    sys.exit(main())
