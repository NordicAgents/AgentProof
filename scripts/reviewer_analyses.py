#!/usr/bin/env python3
"""Reviewer-demanded reanalyses (AAAI rebuttal), all from existing artifacts.

Deterministic, offline, dependency-free (pure Python stdlib). Writes
corpus/real_world/reviewer_analyses.json and prints a compact summary.

Addresses five reviewer points:

  1. SEPARATE ESTIMANDS (construct validity). The paper's 4/119 pooled one
     router/topology (structural) defect with three normative missing-human-gate
     judgments. Split into three estimands with Wilson 95% CIs:
       - structural   (exit/reverse reachability, dead_ends, router_shape,
                        tool_declarations)                 -> 1/119
       - human-gate policy (human_presence, human_gate_coverage) -> 3/119
       - any-confirmed composite (heterogeneous, secondary) -> 4/119
     Cross-checked against gt_triage_results.json real_defect labels + the two
     extractor-visible human_presence confirmed_real reverifications.

  2. POST-STRATIFICATION. Sample composition is not corpus composition. Reweight
     each framework stratum by its corpus share and report a repository-clustered
     bootstrap CI plus an analytic stratified-survey-variance CI, for all three
     estimands. Application-only stratum reported where computable.

  3. FISHER EXACT. App-like 3/39 vs tutorial/demo/test 1/80. Dependency-free
     two-sided Fisher exact (hypergeometric) + sample odds ratio with Wald CI.

  4. FLAG-LEVEL PPV + ROOT-CAUSE DEDUP + BOUNDS. From the 186 as-mined triage
     flags: workflow-level PPV (repo-clustered bootstrap CI), root-cause dedup
     (structural checks sharing a node cluster collapse to one), and the
     confirmed-vs-pessimistic identification range [1.1%, 7.5%] with Wilson CIs.

  5. v2-PRIMARY FIDELITY TABLE. Corrected-instrument (v2) node/edge P/R + kind
     accuracy, overall and per framework, with v1 as-mined as an ablation column.

Usage:
    python scripts/reviewer_analyses.py
"""

from __future__ import annotations

import ast
import json
import math
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RW = ROOT / "corpus" / "real_world"

Z = 1.96
BOOT = 10000
SEED = 20260714

# ---- corpus composition (given): full mined census by framework -------------
CORPUS_N = {"langgraph": 400, "crewai": 113, "autogen": 359, "adk": 50}
CORPUS_TOTAL = 922  # = sum(CORPUS_N)

STRUCTURAL_CHECKS = {
    "exit_reachability", "reverse_reachability", "dead_ends",
    "router_shape", "tool_declarations", "router-non-conditional-edges",
}
POLICY_CHECKS = {"human_presence", "human_gate_coverage",
                 "sensitive-path-bypasses-human-review"}
SELF_REPO_PREFIX = "NordicAgents__AgentProof"

# The four confirmed findings (slug -> (framework, estimand-check, kind)).
# structural = topology/router; policy = missing-human-gate.
CONFIRMED = {
    "gabrielpreda__adk-sql-agent__agent":
        {"framework": "adk", "check": "router_shape", "kind": "structural",
         "source": "gt_triage_results.triage(real_defect)"},
    "Sujas-Aggarwal__langraph-chatbot__v2.6.0":
        {"framework": "langgraph", "check": "human_gate_coverage",
         "kind": "policy", "source": "gt_triage_results.triage(real_defect)"},
    "Jamahl__fraya-25__crew":
        {"framework": "crewai", "check": "human_presence", "kind": "policy",
         "source": "gt_triage_results.reverify(confirmed_real)"},
    "Zen7-Labs__Zen7-Payment-Agent__agent":
        {"framework": "adk", "check": "human_presence", "kind": "policy",
         "source": "gt_triage_results.reverify(confirmed_real)"},
}


# --------------------------------------------------------------------------- #
# Statistics helpers (pure python)
# --------------------------------------------------------------------------- #
def wilson(k: int, n: int, z: float = Z) -> tuple[float, float, float]:
    """Wilson score interval. Returns (p_hat, lo, hi) as proportions."""
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (p, max(0.0, centre - half), min(1.0, centre + half))


def cluster_bootstrap_ratio(clusters: dict, numer_key, denom_key,
                            n_boot: int = BOOT, seed: int = SEED
                            ) -> tuple[float, float, float]:
    """Resample clusters (repos) with replacement; ratio of summed numer/denom.

    clusters: name -> (numer, denom).  Returns (point, lo, hi).
    """
    rng = random.Random(seed)
    names = sorted(clusters)
    tot_n = sum(clusters[c][0] for c in names)
    tot_d = sum(clusters[c][1] for c in names)
    point = tot_n / tot_d if tot_d else 0.0
    vals = []
    for _ in range(n_boot):
        sn = sd = 0.0
        for _ in range(len(names)):
            n_, d_ = clusters[names[rng.randrange(len(names))]]
            sn += n_
            sd += d_
        vals.append(sn / sd if sd else 0.0)
    vals.sort()
    lo = vals[int(0.025 * n_boot)]
    hi = vals[min(int(0.975 * n_boot), n_boot - 1)]
    return point, lo, hi


def stratified_point(strata: dict) -> float:
    """strata: f -> (d_f, n_f).  point = sum_f (N_f/N) * d_f/n_f."""
    p = 0.0
    for f, (d, n) in strata.items():
        if n:
            p += (CORPUS_N[f] / CORPUS_TOTAL) * (d / n)
    return p


def stratified_survey_ci(strata: dict, z: float = Z) -> dict:
    """Analytic stratified-survey variance with finite-population correction.

    Var(p_hat) = sum_f W_f^2 (1 - n_f/N_f) p_f(1-p_f)/n_f.
    Normal CI clamped to [0,1].  Poor for tiny counts -> reported alongside the
    clustered bootstrap, which is the preferred interval here.
    """
    var = 0.0
    for f, (d, n) in strata.items():
        if n == 0:
            continue
        w = CORPUS_N[f] / CORPUS_TOTAL
        p = d / n
        fpc = max(0.0, 1 - n / CORPUS_N[f])
        var += w * w * fpc * p * (1 - p) / n
    se = math.sqrt(var)
    point = stratified_point(strata)
    return {"point": point, "se": se,
            "normal_ci": [max(0.0, point - z * se), min(1.0, point + z * se)]}


def stratified_cluster_bootstrap(strata_clusters: dict,
                                 n_boot: int = BOOT, seed: int = SEED
                                 ) -> tuple[float, float, float]:
    """Repository-clustered bootstrap WITHIN strata with fixed corpus weights.

    strata_clusters: f -> { repo -> (d_repo, n_repo) }.  Each bootstrap draw
    resamples the repos of every framework with replacement (count preserved),
    recomputes d_f*/n_f*, and forms p* = sum_f W_f d_f*/n_f*.
    """
    rng = random.Random(seed)
    point = stratified_point(
        {f: (sum(d for d, _ in cl.values()), sum(n for _, n in cl.values()))
         for f, cl in strata_clusters.items()})
    draws = []
    for _ in range(n_boot):
        p = 0.0
        for f, cl in strata_clusters.items():
            repos = list(cl)
            sd = sn = 0.0
            for _ in range(len(repos)):
                d_, n_ = cl[repos[rng.randrange(len(repos))]]
                sd += d_
                sn += n_
            if sn:
                p += (CORPUS_N[f] / CORPUS_TOTAL) * (sd / sn)
        draws.append(p)
    draws.sort()
    lo = draws[int(0.025 * n_boot)]
    hi = draws[min(int(0.975 * n_boot), n_boot - 1)]
    return point, lo, hi


def fisher_exact_two_sided(a: int, b: int, c: int, d: int) -> float:
    """Two-sided Fisher exact (Fisher-Irwin) for table [[a,b],[c,d]]."""
    r1, r2 = a + b, c + d
    c1 = a + c
    n = a + b + c + d

    def logC(nn: int, kk: int) -> float:
        if kk < 0 or kk > nn:
            return float("-inf")
        return (math.lgamma(nn + 1) - math.lgamma(kk + 1)
                - math.lgamma(nn - kk + 1))

    logden = logC(n, c1)

    def prob(av: int) -> float:
        lp = logC(r1, av) + logC(r2, c1 - av) - logden
        return math.exp(lp)

    p_obs = prob(a)
    lo = max(0, c1 - r2)
    hi = min(r1, c1)
    tol = p_obs * (1 + 1e-7)
    return sum(prob(av) for av in range(lo, hi + 1) if prob(av) <= tol)


def odds_ratio_wald(a: int, b: int, c: int, d: int, z: float = Z):
    """Sample OR + Wald log-OR CI; also Haldane-Anscombe (0.5) corrected."""
    def _or_ci(a_, b_, c_, d_):
        orr = (a_ * d_) / (b_ * c_)
        se = math.sqrt(1 / a_ + 1 / b_ + 1 / c_ + 1 / d_)
        lo = math.exp(math.log(orr) - z * se)
        hi = math.exp(math.log(orr) + z * se)
        return orr, lo, hi, se
    sample = _or_ci(a, b, c, d) if min(a, b, c, d) > 0 else (None, None, None, None)
    hald = _or_ci(a + 0.5, b + 0.5, c + 0.5, d + 0.5)
    return {"sample": sample, "haldane": hald}


# --------------------------------------------------------------------------- #
# Node-set extraction for root-cause dedup
# --------------------------------------------------------------------------- #
def parse_bracket_list(s: str) -> set:
    m = re.search(r"\[.*\]", s or "")
    if not m:
        return set()
    try:
        return {str(x) for x in ast.literal_eval(m.group(0))}
    except Exception:
        return set()


def node_set_for(defect: dict) -> set:
    nodes: set = set()
    w = defect.get("witnesses")
    if isinstance(w, dict):
        nodes |= set(w.keys())
    nodes |= parse_bracket_list(defect.get("detail", ""))
    return nodes


class UF:
    def __init__(self, items):
        self.p = {i: i for i in items}

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


# --------------------------------------------------------------------------- #
def main() -> None:
    gt = json.loads((RW / "gt_triage_results.json").read_text())
    rev = json.loads((RW / "revision_analyses.json").read_text())
    validated = json.loads((RW / "validated_results.json").read_text())
    corrfid = json.loads((RW / "corrected_fidelity.json").read_text())
    cls = {c["slug"]: c for c in gt["classification"]}
    per_wf = rev["prevalence_gt"]["per_workflow"]  # 119 sample workflows

    # sanity: sample composition
    sample_n = Counter(r["framework"] for r in per_wf)
    assert dict(sample_n) == {"langgraph": 40, "adk": 24, "autogen": 35,
                              "crewai": 20}, dict(sample_n)
    assert len(per_wf) == 119
    assert sum(CORPUS_N.values()) == CORPUS_TOTAL

    slug_fw = {r["slug"]: r["framework"] for r in per_wf}
    slug_repo = {r["slug"]: r["repo"] for r in per_wf}

    # ================= 1. SEPARATE ESTIMANDS ================================= #
    struct_slugs = [s for s, m in CONFIRMED.items() if m["kind"] == "structural"]
    policy_slugs = [s for s, m in CONFIRMED.items() if m["kind"] == "policy"]
    assert len(struct_slugs) == 1 and len(policy_slugs) == 3
    assert len(struct_slugs) + len(policy_slugs) == 4  # split sums to 4

    # cross-check against gt_triage real_defect + reverify confirmed_real
    real_defect_flags = [(t["slug"], t["check_id"]) for t in gt["triage"]
                         if t["primary"]["label"] == "real_defect"]
    confirmed_real_reverify = [(r["slug"], r["check"]) for r in gt["reverify"]
                               if r["verdict"] == "confirmed_real"]
    xcheck_union = {s for s, _ in real_defect_flags} | \
                   {s for s, _ in confirmed_real_reverify}
    assert xcheck_union == set(CONFIRMED), (xcheck_union, set(CONFIRMED))

    def estimand_block(slugs, label):
        k = len(slugs)
        p, lo, hi = wilson(k, 119)
        return {"label": label, "k": k, "n": 119,
                "rate": p, "wilson_ci": [lo, hi],
                "slugs": {s: {"framework": CONFIRMED[s]["framework"],
                              "check": CONFIRMED[s]["check"],
                              "category": cls[s]["category"],
                              "source": CONFIRMED[s]["source"]} for s in slugs}}

    estimand_split = {
        "note": ("Three disjoint estimands. Structural = router/topology "
                 "checks; policy = missing-human-gate normative judgments; "
                 "composite = their union, heterogeneous, reported as SECONDARY "
                 "only. Confirmed set = gt_triage real_defect labels (2) + "
                 "reverify confirmed_real human_presence (2)."),
        "structural": estimand_block(struct_slugs, "confirmed_structural_defects"),
        "policy": estimand_block(policy_slugs, "confirmed_human_gate_policy_violations"),
        "composite_any": estimand_block(list(CONFIRMED), "any_confirmed_finding_COMPOSITE_SECONDARY"),
        "split_sums_to_composite": len(struct_slugs) + len(policy_slugs) == len(CONFIRMED),
        "crosscheck": {
            "gt_triage_real_defect_flags": real_defect_flags,
            "reverify_confirmed_real": confirmed_real_reverify,
            "extractor_visible_human_presence_real_defects":
                [s for s, _ in confirmed_real_reverify],
        },
    }

    # ================= 2. POST-STRATIFICATION =============================== #
    # per-estimand, per-framework confirmed-defect indicators (workflow level)
    def indicators(slug_set):
        strata = {f: [0, 0] for f in CORPUS_N}          # f -> [d_f, n_f]
        clusters = {f: defaultdict(lambda: [0, 0]) for f in CORPUS_N}  # f->repo->[d,n]
        for r in per_wf:
            f = r["framework"]
            strata[f][1] += 1
            clusters[f][r["repo"]][1] += 1
            if r["slug"] in slug_set:
                strata[f][0] += 1
                clusters[f][r["repo"]][0] += 1
        strata = {f: (v[0], v[1]) for f, v in strata.items()}
        clusters = {f: {rp: (d, n) for rp, (d, n) in cl.items()}
                    for f, cl in clusters.items()}
        return strata, clusters

    def post_strat_block(slug_set):
        strata, clusters = indicators(set(slug_set))
        k = sum(d for d, _ in strata.values())
        wp, wlo, whi = wilson(k, 119)
        analytic = stratified_survey_ci(strata)
        bpoint, blo, bhi = stratified_cluster_bootstrap(clusters)
        return {
            "per_framework": {f: {"d": d, "n": n,
                                  "rate": (d / n if n else 0.0),
                                  "corpus_weight": CORPUS_N[f] / CORPUS_TOTAL}
                              for f, (d, n) in strata.items()},
            "unweighted_sample_rate": {"k": k, "n": 119, "rate": wp,
                                       "wilson_ci": [wlo, whi],
                                       "note": "VALIDATION-SAMPLE rate only"},
            "post_stratified_point": stratified_point(strata),
            "post_stratified_survey_ci": analytic,
            "post_stratified_cluster_bootstrap_ci":
                {"point": bpoint, "ci95": [blo, bhi],
                 "method": "repo-clustered bootstrap within strata, "
                           f"B={BOOT}, corpus weights fixed"},
        }

    post_stratification = {
        "corpus_composition": dict(CORPUS_N, total=CORPUS_TOTAL),
        "sample_composition": dict(sample_n),
        "structural": post_strat_block(struct_slugs),
        "policy": post_strat_block(policy_slugs),
        "composite_any": post_strat_block(list(CONFIRMED)),
    }

    # application-only stratum (post-stratification within app needs a corpus
    # app census we do not have; report unweighted app-only + non-app rates)
    app_slugs = {s for s, c in cls.items() if c["category"] == "application_like"}
    n_app = sum(1 for r in per_wf if r["slug"] in app_slugs)         # 39
    n_nonapp = 119 - n_app                                            # 80

    def app_split(slug_list):
        ka = sum(1 for s in slug_list if s in app_slugs)
        kn = len(slug_list) - ka
        pa, alo, ahi = wilson(ka, n_app)
        pn, nlo, nhi = wilson(kn, n_nonapp)
        return {"app_like": {"k": ka, "n": n_app, "rate": pa,
                             "wilson_ci": [alo, ahi]},
                "non_app": {"k": kn, "n": n_nonapp, "rate": pn,
                            "wilson_ci": [nlo, nhi]}}

    post_stratification["application_only_stratum"] = {
        "n_app_like": n_app, "n_non_app": n_nonapp,
        "structural": app_split(struct_slugs),
        "policy": app_split(policy_slugs),
        "composite_any": app_split(list(CONFIRMED)),
        "note": ("Framework post-stratification WITHIN the app-like stratum is "
                 "NOT computable: no corpus-level app-vs-tutorial census exists "
                 "in the artifacts. Only unweighted app-like vs non-app rates "
                 "with Wilson CIs are reported."),
    }

    # ================= 3. FISHER EXACT ====================================== #
    a = sum(1 for s in CONFIRMED if s in app_slugs)         # app & defect = 3
    c = len(CONFIRMED) - a                                   # non-app & defect = 1
    b = n_app - a                                            # app & no-defect = 36
    d = n_nonapp - c                                         # non-app & no-defect = 79
    assert (a, b, c, d) == (3, 36, 1, 79), (a, b, c, d)
    p_fisher = fisher_exact_two_sided(a, b, c, d)
    orr = odds_ratio_wald(a, b, c, d)
    sample_or = orr["sample"]
    fisher_exact = {
        "table": {"app_like_defect": a, "app_like_clean": b,
                  "other_defect": c, "other_clean": d,
                  "app_rate": a / n_app, "other_rate": c / n_nonapp},
        "two_sided_p": p_fisher,
        "odds_ratio_sample": {"or": sample_or[0],
                              "wald_ci95": [sample_or[1], sample_or[2]]},
        "odds_ratio_haldane": {"or": orr["haldane"][0],
                               "wald_ci95": [orr["haldane"][1], orr["haldane"][2]]},
        "suggested_wording": (
            "Confirmed defects were concentrated in application-like workflows "
            f"(3/39, 7.7%) relative to tutorial, demo, and test workflows "
            f"(1/80, 1.3%). The difference is suggestive but not statistically "
            f"significant at this sample size (two-sided Fisher exact "
            f"p = {p_fisher:.2f}; odds ratio {sample_or[0]:.1f}, 95% CI "
            f"[{sample_or[1]:.1f}, {sample_or[2]:.0f}], spanning 1). We therefore "
            "frame the application/tutorial gap as a hypothesis-generating "
            "association rather than a confirmed effect, and note the wide "
            "interval reflects the small number of confirmed defects."),
    }

    # ================= 4. FLAG-LEVEL PPV + DEDUP + BOUNDS =================== #
    td = [t for t in validated["triage_details"]
          if not t["slug"].startswith(SELF_REPO_PREFIX)]
    assert len(td) == 186, len(td)
    label_dist = Counter(t["label"] for t in td)
    genuine_flags = [t for t in td if t["label"] == "real_defect"]
    arguable_flags = [t for t in td if t["label"] == "arguable"]

    # ---- workflow-level PPV ----
    by_wf_labels = defaultdict(set)
    for t in td:
        by_wf_labels[t["slug"]].add(t["label"])
    flagged_wf = set(by_wf_labels)
    genuine_wf = {s for s, ls in by_wf_labels.items() if "real_defect" in ls}
    pess_wf = {s for s, ls in by_wf_labels.items()
               if ls & {"real_defect", "arguable"}}
    # repo clusters for workflow-level PPV
    def repo_of(slug):
        return slug_repo.get(slug) or "/".join(slug.split("__")[:2])
    wf_clusters = defaultdict(lambda: [0, 0])   # repo -> [genuine_wf, flagged_wf]
    wf_clusters_pess = defaultdict(lambda: [0, 0])
    for s in flagged_wf:
        rp = repo_of(s)
        wf_clusters[rp][1] += 1
        wf_clusters_pess[rp][1] += 1
        if s in genuine_wf:
            wf_clusters[rp][0] += 1
        if s in pess_wf:
            wf_clusters_pess[rp][0] += 1
    wf_clusters = {k: (v[0], v[1]) for k, v in wf_clusters.items()}
    wf_clusters_pess = {k: (v[0], v[1]) for k, v in wf_clusters_pess.items()}
    wpoint, wlo, whi = cluster_bootstrap_ratio(wf_clusters, 0, 1)
    ppoint, plo, phi = cluster_bootstrap_ratio(wf_clusters_pess, 0, 1, seed=SEED + 1)

    _, wilw_lo, wilw_hi = wilson(len(genuine_wf), len(flagged_wf))

    workflow_ppv = {
        "definition": "fraction of FLAGGED workflows with >=1 genuine flag",
        "n_flagged_workflows": len(flagged_wf),
        "n_genuine_workflows": len(genuine_wf),
        "confirmed": {"ppv": len(genuine_wf) / len(flagged_wf),
                      "wilson_ci": [wilw_lo, wilw_hi],
                      "repo_cluster_bootstrap_ci": [wlo, whi]},
        "pessimistic_genuine_or_arguable": {
            "n": len(pess_wf), "ppv": len(pess_wf) / len(flagged_wf),
            "repo_cluster_bootstrap_ci": [plo, phi]},
    }

    # ---- root-cause dedup ----
    dr = json.loads((RW / "defect_results.json").read_text())
    drmap = defaultdict(dict)
    for wf in dr["details"]:
        for df in wf.get("defects", []):
            drmap[wf["name"]][df["check"]] = df

    RANK = {"real_defect": 3, "arguable": 2, "intentional": 1,
            "extraction_artifact": 0}
    flags_by_wf = defaultdict(list)
    for t in td:
        flags_by_wf[t["slug"]].append(t)

    dedup_groups = []      # each group -> worst label
    unmatched_detail = 0
    for slug, flags in flags_by_wf.items():
        struct = [f for f in flags if f["check"] in STRUCTURAL_CHECKS]
        nonstruct = [f for f in flags if f["check"] not in STRUCTURAL_CHECKS]
        # union-find struct flags by shared node cluster
        idx = list(range(len(struct)))
        uf = UF(idx)
        nsets = []
        for f in struct:
            df = drmap.get(slug, {}).get(f["check"])
            if df is None:
                unmatched_detail += 1
                nsets.append(set())
            else:
                nsets.append(node_set_for(df))
        for i in range(len(struct)):
            for j in range(i + 1, len(struct)):
                if nsets[i] and nsets[j] and (nsets[i] & nsets[j]):
                    uf.union(i, j)
        comp = defaultdict(list)
        for i in idx:
            comp[uf.find(i)].append(struct[i])
        for members in comp.values():
            worst = max(members, key=lambda m: RANK[m["label"]])
            dedup_groups.append(worst["label"])
        for f in nonstruct:
            dedup_groups.append(f["label"])

    dedup_counter = Counter(dedup_groups)
    n_dedup = len(dedup_groups)
    dedup_genuine = dedup_counter.get("real_defect", 0)
    dedup_arguable = dedup_counter.get("arguable", 0)
    _, dg_lo, dg_hi = wilson(dedup_genuine, n_dedup)
    _, dp_lo, dp_hi = wilson(dedup_genuine + dedup_arguable, n_dedup)

    root_cause_dedup = {
        "rule": ("within a workflow, structural flags whose node clusters "
                 "intersect collapse to one root-cause group (e.g. one missing "
                 "edge firing exit_reachability + reverse_reachability + "
                 "dead_ends counts once); non-structural policy flags are kept "
                 "individually. Node clusters read from defect_results.json."),
        "raw_flag_count": 186,
        "deduplicated_flag_count": n_dedup,
        "flags_collapsed": 186 - n_dedup,
        "dedup_label_distribution": dict(dedup_counter),
        "structural_flags_without_node_detail_kept_standalone": unmatched_detail,
        "confirmed_ppv": {"k": dedup_genuine, "n": n_dedup,
                          "ppv": dedup_genuine / n_dedup,
                          "wilson_ci": [dg_lo, dg_hi]},
        "pessimistic_ppv": {"k": dedup_genuine + dedup_arguable, "n": n_dedup,
                            "ppv": (dedup_genuine + dedup_arguable) / n_dedup,
                            "wilson_ci": [dp_lo, dp_hi]},
    }

    # ---- confirmed vs pessimistic identification range ----
    n_flags = 186
    k_conf = len(genuine_flags)                 # 2
    k_pess = k_conf + len(arguable_flags)       # 14
    _, c_lo, c_hi = wilson(k_conf, n_flags)
    _, pe_lo, pe_hi = wilson(k_pess, n_flags)
    ppv_bounds = {
        "flag_universe": "186 AS-MINED triage flags (self-repo excluded)",
        "label_distribution": dict(label_dist),
        "confirmed_only": {"k": k_conf, "n": n_flags, "ppv": k_conf / n_flags,
                           "wilson_ci": [c_lo, c_hi]},
        "pessimistic_all_arguable_genuine": {
            "k": k_pess, "n": n_flags, "ppv": k_pess / n_flags,
            "wilson_ci": [pe_lo, pe_hi]},
        "identification_range_before_sampling_uncertainty":
            [k_conf / n_flags, k_pess / n_flags],
        "note": ("The 2 confirmed are both human_presence policy gaps found by "
                 "the AS-MINED extractor; all 72 as-mined STRUCTURAL flags were "
                 "extraction artifacts / gt_errors (0 genuine). The one confirmed "
                 "STRUCTURAL defect (gabrielpreda router_shape, estimand #1) came "
                 "from the corrected GT-graph re-run, a different flag universe."),
    }

    flag_ppv = {
        "workflow_level_ppv": workflow_ppv,
        "root_cause_dedup": root_cause_dedup,
        "ppv_bounds": ppv_bounds,
    }

    # ================= 5. v2-PRIMARY FIDELITY TABLE ======================== #
    v1 = corrfid["fidelity_v1_asmined"]
    v2 = corrfid["fidelity_v2_corrected"]
    metrics = ["node_precision", "node_recall", "edge_precision",
               "edge_recall", "kind_accuracy"]

    def row(v2blk, v1blk):
        r = {"n_v2": v2blk["n"], "n_v1": v1blk["n"]}
        for m in metrics:
            r[m] = {"v2_primary": v2blk[m], "v1_asmined_ablation": v1blk[m],
                    "delta": round(v2blk[m] - v1blk[m], 3)}
        return r

    fidelity_v2_table = {
        "note": corrfid["note"],
        "node_pr_per_framework_source": ("present in corrected_fidelity.json "
                                         "(node_precision/node_recall per "
                                         "framework); no recomputation needed"),
        "overall": row(v2["overall"], v1["overall"]),
        "per_framework": {fw: row(v2["per_framework"][fw], v1["per_framework"][fw])
                          for fw in sorted(v2["per_framework"])},
        "flag_volume": {"v1_asmined": corrfid["flags_v1_asmined"],
                        "v2_corrected": corrfid["flags_v2_corrected"]},
    }

    # ================= ASSEMBLE + WRITE ==================================== #
    out = {
        "_meta": {
            "generated_from": "existing offline artifacts only",
            "corpus_composition": dict(CORPUS_N, total=CORPUS_TOTAL),
            "sample_composition": dict(sample_n),
            "bootstrap_B": BOOT, "seed": SEED, "z": Z,
        },
        "1_separate_estimands": estimand_split,
        "2_post_stratification": post_stratification,
        "3_fisher_exact": fisher_exact,
        "4_flag_ppv": flag_ppv,
        "5_fidelity_v2_table": fidelity_v2_table,
    }
    (RW / "reviewer_analyses.json").write_text(json.dumps(out, indent=2))

    # ================= COMPACT SUMMARY ===================================== #
    def pct(x):
        return f"{100 * x:5.2f}%"

    def ci(lo, hi):
        return f"[{100*lo:5.2f},{100*hi:5.2f}]"

    print("=" * 74)
    print("REVIEWER REANALYSES  (all from artifacts, seed=%d, B=%d)" % (SEED, BOOT))
    print("=" * 74)
    print("\n[1] SEPARATE ESTIMANDS (Wilson 95% CI)")
    for key in ("structural", "policy", "composite_any"):
        blk = estimand_split[key]
        print(f"  {blk['label']:44} {blk['k']}/119 = {pct(blk['rate'])} "
              f"{ci(*blk['wilson_ci'])}")
    print(f"  split sums to composite: {estimand_split['split_sums_to_composite']}")

    print("\n[2] POST-STRATIFICATION (corpus-weighted)")
    print(f"  {'estimand':13} {'unwt sample':>12} {'post-strat':>11}  "
          f"{'bootstrap CI':>16}  {'survey CI':>16}")
    for key in ("structural", "policy", "composite_any"):
        b = post_stratification[key]
        us = b["unweighted_sample_rate"]
        pp = b["post_stratified_point"]
        bc = b["post_stratified_cluster_bootstrap_ci"]["ci95"]
        sc = b["post_stratified_survey_ci"]["normal_ci"]
        print(f"  {key:13} {us['k']}/119={pct(us['rate'])} {pct(pp)}  "
              f"{ci(*bc)}  {ci(*sc)}")
    ao = post_stratification["application_only_stratum"]
    print(f"  app-only composite: {ao['composite_any']['app_like']['k']}/"
          f"{ao['composite_any']['app_like']['n']}="
          f"{pct(ao['composite_any']['app_like']['rate'])}  "
          f"non-app: {ao['composite_any']['non_app']['k']}/"
          f"{ao['composite_any']['non_app']['n']}="
          f"{pct(ao['composite_any']['non_app']['rate'])}")

    print("\n[3] FISHER EXACT  app-like 3/39 vs other 1/80")
    print(f"  two-sided p = {p_fisher:.4f}   OR(sample) = {sample_or[0]:.2f} "
          f"Wald95% [{sample_or[1]:.2f},{sample_or[2]:.1f}]")

    print("\n[4] FLAG PPV / DEDUP / BOUNDS  (186 as-mined flags)")
    wc = workflow_ppv["confirmed"]
    print(f"  workflow-level PPV: {workflow_ppv['n_genuine_workflows']}/"
          f"{workflow_ppv['n_flagged_workflows']} = {pct(wc['ppv'])} "
          f"bootCI {ci(*wc['repo_cluster_bootstrap_ci'])}")
    print(f"  root-cause dedup: 186 -> {n_dedup} flags "
          f"({186 - n_dedup} collapsed); confirmed PPV "
          f"{dedup_genuine}/{n_dedup} = {pct(dedup_genuine / n_dedup)}")
    cb = ppv_bounds["confirmed_only"]
    pb = ppv_bounds["pessimistic_all_arguable_genuine"]
    print(f"  identification range: confirmed {cb['k']}/186={pct(cb['ppv'])} "
          f"{ci(*cb['wilson_ci'])}  ->  pessimistic {pb['k']}/186="
          f"{pct(pb['ppv'])} {ci(*pb['wilson_ci'])}")

    print("\n[5] v2 FIDELITY (primary) vs v1 as-mined (ablation)")
    ov = fidelity_v2_table["overall"]
    print(f"  overall n(v2)={ov['n_v2']} n(v1)={ov['n_v1']}")
    for m in metrics:
        print(f"    {m:15} v2={ov[m]['v2_primary']:.3f}  "
              f"v1={ov[m]['v1_asmined_ablation']:.3f}  "
              f"d={ov[m]['delta']:+.3f}")
    print("  per-framework node/edge P-R, kind (v2 | v1):")
    for fw in sorted(fidelity_v2_table["per_framework"]):
        r = fidelity_v2_table["per_framework"][fw]
        print(f"    {fw:9} nP {r['node_precision']['v2_primary']:.2f}|"
              f"{r['node_precision']['v1_asmined_ablation']:.2f}  "
              f"nR {r['node_recall']['v2_primary']:.2f}|"
              f"{r['node_recall']['v1_asmined_ablation']:.2f}  "
              f"eP {r['edge_precision']['v2_primary']:.2f}|"
              f"{r['edge_precision']['v1_asmined_ablation']:.2f}  "
              f"eR {r['edge_recall']['v2_primary']:.2f}|"
              f"{r['edge_recall']['v1_asmined_ablation']:.2f}  "
              f"k {r['kind_accuracy']['v2_primary']:.2f}|"
              f"{r['kind_accuracy']['v1_asmined_ablation']:.2f}")
    print("\nwritten -> corpus/real_world/reviewer_analyses.json")


if __name__ == "__main__":
    main()
