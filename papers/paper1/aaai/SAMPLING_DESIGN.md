# Sampling Design, Frame Construction, and the Limits of the Corpus

Reviewer-facing methods documentation for the real-world mining study
(`papers/paper1/aaai/sections/03_realworld.tex`). Reconstructed entirely from the
artifacts in this repository. **No `.tex` file was modified by this document.**

Bottom line up front, stated plainly:

> The 922-graph corpus is a **search-ranked convenience corpus**, not a probability
> sample of GitHub agent workflows. The 119-graph validation set is a **hand-fixed,
> unseeded, quota-shaped subset** of that corpus, hard-coded into a driver script; no
> sampler, no seed, and no reproducible selection rule exists in the repository.
> Inclusion probabilities are therefore not merely unestimated — they are **undefined**.
> Every framework-share reweighting in the paper is a **weighted descriptive statistic
> over a convenience corpus**, not a design-based prevalence estimate for GitHub.

---

## 1. Population, frame, and what the frame is not

### 1.1 Target population (as implicitly claimed)
"Agent workflow definitions written with LangGraph, CrewAI, AutoGen, or Google ADK in
public GitHub repositories."

### 1.2 What was actually enumerated (the frame)
The frame is **the set of files returned by 11 GitHub code-search queries, truncated by
a per-query result cap and a global repository-list cap, in GitHub's opaque relevance
("best match") order** — then all `*.py` files inside the repositories that survived
that truncation.

This frame is **not** the target population. Specifically it excludes, with unknown and
non-uniform probability:

- repositories GitHub's code-search index does not cover (forks are excluded by default;
  index coverage of small/inactive/large repos is undocumented and changes over time);
- everything ranked below position 40 for every one of the 11 queries;
- everything whose *repository* ranked below position 180 in the concatenated candidate
  list (see §2.3) — this is precisely why the first mining run recovered **zero** AutoGen
  and ADK graphs and required a second, framework-filtered run
  (`corpus/real_world/FINDINGS.md:12-15`);
- any workflow phrased so that it matches none of the 11 literal token queries.

It also *over*-includes, relative to any notion of "deployed agent workflows": tutorial
repos, course material, demos, and tests are in the frame by construction (the source-level
census in `gt_triage_results.json` finds only **39 of 119** sampled workflows are
`application_like`).

---

## 2. Frame construction: exact queries, caps, ordering, dates

### 2.1 The 11 queries
`scripts/mine_github_gh.py:37-49`, executed via `gh search code` (authenticated `gh` CLI):

| framework | query string (verbatim) |
|---|---|
| langgraph | `StateGraph add_node language:python` |
| langgraph | `StateGraph add_conditional_edges language:python` |
| langgraph | `from langgraph.graph add_edge language:python` |
| crewai | `from crewai Crew Task language:python` |
| crewai | `crewai "process=Process" language:python` |
| autogen | `GroupChat autogen language:python` |
| autogen | `RoundRobinGroupChat language:python` |
| autogen | `SelectorGroupChat language:python` |
| adk | `SequentialAgent google.adk language:python` |
| adk | `from google.adk Agent language:python` |
| adk | `ParallelAgent google.adk language:python` |

(An older PyGithub variant with quoted-phrase equivalents lives at
`scripts/scrape_workflows.py:24-41`; it also carries a third CrewAI query,
`language:Python "from crewai" "sequential"`, which the `gh` path does **not** use.
The `gh` path is the one that produced the corpus.)

### 2.2 Caps and ordering — the decisive detail
- **Per-query result cap: 40.** `gh search code ... --limit 40`
  (`scripts/mine_github_gh.py:52-58`, default `--per-query 40` at line 295).
  Confirmed by the artifact: `candidates.json` holds **341** items over 11 queries;
  AutoGen alone contributes exactly 120 = 3 x 40.
- **No sort key is ever passed.** `gh search code` therefore returns GitHub's default
  **"best match" relevance ranking** — a proprietary, undocumented, non-stationary
  function of text match, repo popularity, and recency. Every subsequent truncation
  inherits this ordering.
- **Repository-list truncation: `unique[:max_repos]`**, `max_repos` default 120,
  run at 180. Two identical code paths:
  `scripts/mine_github_gh.py:125` (`clone_repos`) and
  `scripts/mine_github_gh.py:231` (`stream_mine`). The unique-repo list is built by
  **first appearance in `candidates.json` order** (lines 122-125 / 228-231), i.e. in
  search-relevance order, and then cut.
  **Verified against the artifact:** `repos.lg_crew.json` (180 repos) is exactly the
  first 180 unique repositories of `candidates.json` in candidate order — set-identical.
  The truncation is real, is rank-ordered, and is what dropped AutoGen/ADK from run 1.
- **No per-repository file cap.** `find_workflow_files`
  (`scripts/scrape_workflows.py:139-151`) walks **every** `*.py` file under the clone via
  `rglob`, skipping only dot-dirs, `venv`/`.venv`, `node_modules`, `__pycache__`.
  A single repo may therefore contribute unboundedly many graphs.
  *The paper's phrase "per-repository caps" is inaccurate: the cap is on the repository
  list, not on files per repository.*
- **Framework assignment is a text heuristic**, not a dependency check: a file is labeled
  with framework `f` if >=2 of `f`'s marker tokens appear anywhere in it
  (`scripts/scrape_workflows.py:126-136`). A README-like or multi-framework file can be
  mislabeled; a workflow importing two frameworks is assigned to whichever dict key comes
  first.

### 2.3 The two mining runs
1. **Run 1 (LangGraph/CrewAI).** Full 341-candidate list, `--max-repos 180`. AutoGen and
   ADK extraction did not exist in the extractor yet (added in commit `743392a`), so the
   180-repo prefix yielded 282 extracted records over 149 repos, LangGraph + CrewAI only
   -> `metadata.lg_crew.json`, `repos.lg_crew.json`.
2. **Run 2 (AutoGen/ADK).** `--frameworks autogen,adk` filter
   (`scripts/mine_github_gh.py:326-330`), 139 unique repos — the 180 cap was not binding
   here — 798 extracted records -> `metadata.json`, `repos.json`.

Union: **318 candidate repositories**, of which 253 yielded >=1 extracted graph.

### 2.4 Mining date
**11 July 2026** (single day, two runs). Established independently in
`corpus/real_world/MINING_DATE_FORENSICS.md`: the newest pinned commit SHA in the corpus is
`2026-07-11T00:56:23Z` (a hard lower bound), and the commits that introduced the artifacts
are dated `2026-07-11T15:15` / `19:01 +01:00` (an upper bound).
The paper's current claim of "February--March 2026" is **falsified by the artifacts**:
51 of 318 pinned SHAs post-date 2026-03-31, and one corpus repository was not created until
2026-03-03. Every graph is pinned to a specific `(repo, commit SHA, path)` and was
re-extracted at that pin by `scripts/remine_pinned.py` -> `metadata_v2.json`, so the
snapshot is reproducible even though the *search* is not.

### 2.5 An undocumented silent de-duplication (found during this audit)
Graph filenames are `slug = <owner>__<repo>__<file stem>`
(`scripts/mine_github_gh.py:170`, `:256`) and are written with a plain overwrite
(`out_dir / f"{slug}.json"`). Two files with the same basename in the same repository
therefore collapse to one graph, last-writer-wins.

- extracted records across both metadata files: **1080**
- distinct slugs / graphs on disk: **930**
- **150 extracted graphs (13.9%) were silently overwritten.**
- Worst case: `ed-donner/agents` (a tutorial course repo) produced **55** files that all
  collapsed into the single slug `ed-donner__agents__sidekick`.

This is a non-random thinning that further decouples the corpus from any file-level
population, and it is not mentioned in the paper.

---

## 3. The 119-graph validation sample: the selection procedure, reconstructed

### 3.1 Where the sample physically lives
The validation sample is **not computed anywhere**. It exists only as a hard-coded
JavaScript array literal:

- `scripts/wf_run.js`, `const GT = [...]` — **60 items: LangGraph 40, CrewAI 20**
- `scripts/wf_run_v2.js`, `const GT = [...]` — **60 items: AutoGen 35, ADK 25**

Total **120**; the ADK self-repo item `NordicAgents__AgentProof__test_extract_adk` is
dropped downstream, giving the paper's **119** (LangGraph 40, CrewAI 20, AutoGen 35,
**ADK 24**) from **87 repositories**.

A repo-wide grep for a selected slug (`SAMAR-CODE404__backend__report_agent`) returns only
`scripts/wf_run.js` plus derived result JSONs. **There is no sampler script, no manifest,
and no record of how the 120 were chosen.** The absolute paths embedded in those arrays
(`/Users/mx/Documents/Work/MX/Research/Safe/...`) point to a different machine and a
different repository name, so the list was produced outside this repository's history.

### 3.2 Is it random? Seeded? Deterministic-by-order?
**None of the above, as far as the artifacts can show.** Tested and *refuted*
hypotheses (per framework, against the corpus in mining order):

| candidate rule | result |
|---|---|
| first-*k* prefix in mining order | **no** (all four frameworks) |
| first-*k* after dropping <3-node graphs | **no** |
| first-*k* with one graph per repository | **no** |
| top-*k* by graph size | **no** |
| round-robin over repositories in mining order | **no** (best overlap 15/25, ADK) |

Selected positions within each framework's pool are scattered across the whole pool
(e.g. LangGraph picks land at ranks 2 ... 391 of 402; ADK at 0 ... 52 of 53), and the
sample contains up to **4 graphs from the same repository**
(`MikhailMostWanted/Astra`, `blueming333/aicraft-class-autogen`, `merdandt/SalesShortcut`),
which rules out one-per-repo designs.

**There is no random seed anywhere in the selection.** The only seeded sampler in the
repository is `scripts/make_annotation_samples.py` (`--seed`, default **20260713**,
`scripts/make_annotation_samples.py:462`, `rng = random.Random(args.seed)` at line 485).
That script draws the *human-annotation* sub-samples (32-workflow reconstruction sample,
32-workflow no-flag audit) and it draws them **from the 119**, not from the corpus — it
consumes `revision_analyses.json`'s `prevalence_gt.per_workflow` list, i.e. it inherits
the 119 as a fixed given. It does not, and cannot, document how the 119 arose.

**Honest characterization:** the 119 is a **fixed, hand-assembled, framework-quota'd
selection of convenience** (40/20/35/25 quotas are evidently intentional; the members
within each quota are not reconstructible). It is reproducible only in the trivial sense
that the list is checked into the repo.

### 3.3 Achieved sampling fractions (descriptive, not design)

| framework | corpus *N* | sample *n* | *n/N* |
|---|---|---|---|
| LangGraph | 400 | 40 | 10.0% |
| AutoGen | 357 | 35 | 9.8% |
| CrewAI | 115 | 20 | 17.4% |
| ADK | 50 | 24 | **48.0%** |
| **total** | **922** | **119** | 12.9% |

ADK is over-represented ~5x relative to LangGraph. This is the entire motivation for the
reweighting in §5 — and the reason the reweighting cannot be dropped, only correctly
labeled.

---

## 4. Why inclusion probabilities are unavailable

They are not "hard to estimate". They are **undefined**. Four independent reasons, each
sufficient on its own:

1. **The first-stage selection is a proprietary ranking, not a randomization.** `gh search
   code` with no `--sort` returns GitHub's "best match" order. That function is
   undisclosed, non-stationary (it changes as repos gain stars/commits and as the index is
   rebuilt), and deterministic given the index. Truncating it at 40 gives every candidate
   an inclusion indicator of 0 or 1, not a probability. There is no `pi_i` to compute
   and no way to bound it.
2. **The frame's denominator is unknown.** GitHub does not publish the size or membership
   of the code-search index, and no total-hit count was recorded at mining time
   (`gh_search` at `mine_github_gh.py:52-70` discards everything except the capped item
   list). Even a Horvitz-Thompson estimator with guessed weights has no *N* to expand to.
3. **The second stage compounds the first deterministically.** `unique[:180]`
   (`mine_github_gh.py:125`, `:231`) is a hard cut on the same rank order — an
   entire framework (AutoGen, ADK) fell below it in run 1. That is a selection mechanism
   correlated with the ranking signal, not with anything exchangeable.
4. **The third stage is a census, not a sample, with a non-random thinning.** Within a
   surviving repo, all `*.py` files are taken (so cluster sizes are wildly unequal:
   1 to 55 files per repo), and the slug-collision overwrite in §2.5 then deletes 150 of
   them by filename coincidence.

Add the fourth stage — the unreconstructible hand-selection of the 119 — and there is no
level of the design at which a probability model can be attached.

**Consequence:** no design-based variance estimator is licensed. The Wilson intervals and
the repository-clustered bootstrap in the paper are legitimate as *model-based
uncertainty for the 119 observations under an i.i.d.-within-stratum assumption*, and are
the right thing to report, but they quantify **only** sampling noise **within the corpus**.
They carry **no** coverage guarantee for GitHub. The dominant error term — selection bias
of the corpus itself — is unquantified and unquantifiable from these artifacts.

---

## 5. The framework-share reweighting: what it is and is not

`scripts/reviewer_analyses.py:326-372` post-stratifies each per-framework rate by the
corpus framework shares:

```
p_hat = sum_f (N_f / N) * (d_f / n_f)      # reviewer_analyses.py:131, :180, :352
```

with weights hard-coded at `scripts/reviewer_analyses.py:57`, and CIs from a
repository-clustered bootstrap within strata (fixed weights).

**Correct name for this quantity:** a **corpus-share-weighted descriptive statistic** —
the defect rate the 922-graph corpus would show *if* each framework's 119-sample rate held
across that framework's corpus members. It is a *within-corpus* standardization that
removes the ADK over-representation of §3.3.

**What it is not:**
- It is **not** a prevalence estimate for GitHub, or for "agent workflows in the wild".
  The weights `N_f/N` are the composition of a convenience corpus, not of any population.
- It is **not** post-stratification in the survey sense. Post-stratification requires
  known *population* control totals; here the control totals are the corpus's own counts,
  so the procedure cannot correct any bias introduced *before* the corpus existed — which
  is all of the bias.
- The finite-population correction applied at `reviewer_analyses.py:148`
  (`fpc = 1 - n/N_f`) is **not licensed**: an FPC presupposes simple random sampling
  without replacement from `N_f`, which §3.2 shows did not happen. It narrows the
  intervals on an assumption the design does not support. The clustered-bootstrap interval
  is the more defensible of the two and should be the one quoted.

---

## 6. Verification of the reported numbers (and one real error)

### 6.1 Corpus census — **confirmed**
- Graphs on disk: 930; minus 8 self-repo (`NordicAgents/AgentProof`) graphs = **922**. OK
- Repositories: 253 minus the self-repo = **252**. OK
- Mining totals: 318 candidate repositories, 341 candidate files, 1080 extracted records
  collapsing to 930 slugs (§2.5).

### 6.2 Corpus framework mix — **the paper is WRONG on two frameworks**

| framework | paper (`03_realworld.tex:20-21`) | artifacts (`metadata_v2.json`, 922 non-self; identical in the v1 metadata) | |
|---|---|---|---|
| LangGraph | 400 | **400** | OK |
| AutoGen | 359 | **357** | **-2** |
| CrewAI | 113 | **115** | **+2** |
| ADK | 50 | **50** | OK |
| total | 922 | 922 | (sums correct by cancellation) |

The error is a self-repo bookkeeping slip: the 8 excluded self-repo graphs are
LangGraph 2 / AutoGen 2 / CrewAI 1 / ADK 3, but the paper subtracted 0 from AutoGen and 3
from CrewAI. Because the two errors cancel, the total still reads 922, which is why it
survived review. The v1 and v2 metadata agree exactly (zero framework relabels between
them), so this is not a v1/v2 versioning artifact — it is simply wrong.

**Propagation:** the same wrong weights are hard-coded at `scripts/reviewer_analyses.py:57`
(`{"langgraph": 400, "crewai": 113, "autogen": 359, "adk": 50}`) and drive every
reweighted number. Recomputing with the correct 400/115/357/50:

| estimand | published weighted point | corrected | delta |
|---|---|---|---|
| structural | 0.226% | 0.226% | 0.000 pp |
| human-gate policy | 1.923% | 1.934% | +0.011 pp |
| composite | 2.149% | 2.160% | +0.011 pp |

The numerical impact is negligible (<0.02 pp, invisible at the paper's 2-decimal
reporting), but the census sentence and the constant should both be corrected, and the
correction noted, rather than left for a reviewer to find.

### 6.3 Validation-sample composition — **confirmed**
`revision_analyses.json` -> `prevalence_gt.per_workflow`: **n = 119**, LangGraph 40,
AutoGen 35, ADK 24, CrewAI 20, drawn from **87 distinct repositories**, self-repo entries
absent. Matches `03_realworld.tex:32` exactly. The upstream driver lists total 120; the
single dropped item is `NordicAgents__AgentProof__test_extract_adk`, consistent with
`CLAIMS_AUDIT.md` rows A5 and R8.

---

## 7. What the design does support

To be fair to the study, the following claims survive intact and should be stated as the
paper's actual contribution:

- **Descriptive claims about this corpus**, with full provenance: every graph is pinned to
  `(repo, SHA, path)` and re-extractable (`remine_pinned.py`, `metadata_v2.json`).
- **Instrument-fidelity claims** (AST extractor vs. reconstructed reference graphs). These
  are properties of the *instrument on these inputs* and do not require the inputs to be a
  probability sample.
- **The existence/direction findings**: that confirmed structural defects are *rare* even
  in a corpus deliberately enriched toward the frameworks' most-searchable idioms, and
  that most flags are extraction artifacts, is a robust qualitative conclusion. A biased
  frame makes a *low* observed rate more, not less, notable — provided one does not attach
  a population number to it.
- **Relative comparisons within the corpus** (application-like vs. tutorial strata), which
  the paper already reports with an honest non-significant Fisher p = 0.10.

What it does **not** support: any sentence of the form "X% of agent workflows on GitHub".

---

## 8. Reproducibility of the frame

For completeness: the frame itself is **not reproducible**. Re-running the 11 queries today
returns a different top-40 per query (index and ranking have both moved on since
2026-07-11). What *is* reproducible is the corpus **given** `candidates.json` /
`repos*.json`: `scripts/remine_pinned.py` re-fetches every pinned SHA and re-extracts, and
reports its failure modes by category (`repo_unreachable` 13, `no_graph` 5, `extracted`
912 of 930 as of the last run). Reproducibility claims in the paper should be scoped to
"the corpus is reproducible from the pinned manifest", never to "the mining is
reproducible".
