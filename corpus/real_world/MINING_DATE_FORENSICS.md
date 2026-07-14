# Mining-Date Forensics

Question: `papers/paper1/aaai/sections/03_realworld.tex` (line 11) says GitHub
mining ran "February--March 2026". Git history says the mining artifacts first
appeared 2026-07-11. What do the artifacts actually support?

Method note: all pinned-SHA commit dates below were fetched on 2026-07-13 via
`gh api repos/<repo>/commits/<sha> --jq .commit.committer.date` (authenticated,
all 318 corpus repos resolved, 0 errors). Raw per-repo output:
`/tmp/claude-1006/-home-midhun-Documents-MX-Research-AgentProof/72b89fb3-f25c-409f-b844-08bc05631257/scratchpad/pinned_dates_full.json`.

## 1. Evidence table

| Source | Date | What it bounds |
|---|---|---|
| Pinned commit dates, all 318 corpus repos (`repos.json` + `repos.lg_crew.json`, GitHub API) | min 2023-10-25, **max 2026-07-11T00:56:23Z** (`faresrafat3/ai-earth` @ `a3b94466`) | **Hard lower bound on mining time: mining cannot predate the newest pinned snapshot. 51 of 318 pinned SHAs are dated after 2026-03-31; 44 of those repos have `status: extracted` graphs in the corpus. Feb--Mar 2026 mining is impossible.** |
| Per-run maxima | lg_crew run (LangGraph/CrewAI): max pin 2026-07-10T16:06Z; autogen/adk run: max pin 2026-07-11T00:56Z | Both mining runs happened on or after 2026-07-10/11, i.e. essentially the day the artifacts were committed. |
| Single decisive example | `M-H-Amini/PerGent-Agentic-Persona-Generation` @ `f9f94e6c`: pinned commit 2026-05-26; repo **created 2026-03-03**, pushed 2026-05-26; 2 extracted graphs in `metadata.json` | This corpus repo barely existed in the claimed window and its pinned snapshot is ~2 months after it closed. |
| `git log --follow` on `corpus/real_world/{candidates.json, metadata.json, repos.json, wf_output.json, graphs/}` | First appear in `728298c` "feat: real-world GitHub mining study for ICLR", **author date 2026-07-11T15:15:08+01:00**; expanded in `e936b1b` (author 2026-07-11T19:01:36+01:00); no corpus/real_world path exists in any earlier commit | Upper-bound side: mining outputs existed by 2026-07-11 afternoon. Combined with the pinned-SHA lower bound (2026-07-11T00:56Z), mining ran **on 2026-07-11**. |
| `corpus/real_world/FINDINGS.md` line 3 | "Started 2026-07-11 for the ICLR 2027 submission" | Contemporaneous author statement matching the git and API evidence. |
| Background job `metadata_v2.json` summary (partial, 7 records at read time) | `pinned_commit_date_max: 2025-10-23T13:08:40+05:30` | Consistent lower bound (>= Oct 2025 already on 7 records); the full 318-repo scan above supersedes it with 2026-07-11. |
| In-file timestamps in `candidates.json` / `metadata.json` / `repos.json` / `wf_output*.json` | none — records carry only `repo`, `sha`, `file_path`, `stars`, `url`, `status` | The mining pipeline (`scripts/mine_github_gh.py`) records no run timestamps and its queries contain no date qualifiers; JSONs alone cannot date the run, hence the API cross-check. |
| `papers/paper1/references.bib` | `Accessed: 2026-02-28` (5 entries) and `Accessed: 2026-03-01` (8 entries) on documentation citations | Bounds only when the *documentation* was consulted. Matches the repo's Feb--Mar 2026 development window (commits 2026-02-13 .. 2026-03-26: AgentProof tool + first paper drafts) — the likely origin of the erroneous "February--March 2026" phrase. |
| `git log -S 'February--March 2026'` | Phrase introduced in `8cc551e` (author 2026-07-13T06:53:30+01:00), the AAAI review-response commit; it appears **only** in the AAAI version, not in `papers/paper1/arxiv/sections/06a_realworld_study.tex` (which states no date) | The claim is a 2026-07-13 editorial addition, not something carried from a Feb--Mar record. |
| `PROGRESS.md` | "Status as of 2026-07-13"; item 5 notes mining query strings live in `scripts/mine_github_gh.py` | Consistent with a July work window; no Feb--Mar mining statement anywhere in the repo. |

## 2. Verdict

The artifacts **contradict "February--March 2026"** and support **mining on
2026-07-11** (single day, two runs: LangGraph/CrewAI first, then
AutoGen/ADK + expansion).

- Impossibility: 51 of the 318 pinned repository snapshots are dated after
  2026-03-31, including 44 repos that contribute extracted graphs to the 922-
  graph corpus; one corpus repo was not even created until 2026-03-03. A
  Feb--Mar 2026 code search could not have returned these SHAs.
- Positive dating: the newest pinned snapshot (2026-07-11T00:56Z) and the git
  author dates of the commits that introduced the artifacts
  (2026-07-11T15:15 / 19:01 +01:00) bracket the mining to 2026-07-11, matching
  FINDINGS.md ("Started 2026-07-11").
- The "February--March 2026" phrase was added on 2026-07-13 in the AAAI
  revision (`8cc551e`) and most plausibly conflates the mining date with the
  Feb--Mar 2026 tool-development window (repo history 2026-02-13..2026-03-26;
  bib "Accessed" dates 2026-02-28/2026-03-01). Those dates bound documentation
  access and tool development, not the corpus.
- Caveat on committer dates: git committer dates are author-controlled and a
  pinned SHA could in principle carry a forged future date, but 51 independent
  repos (including microsoft/ACV, Azure/mcp-kubernetes, docker/compose-for-agents,
  nokia/mcp-redfish) all post-dating March and none post-dating 2026-07-11 is
  not explicable by clock skew; the convergence with git author dates and
  FINDINGS.md settles it.

## 3. Recommended paper wording

In `papers/paper1/aaai/sections/03_realworld.tex`, replace the sentence
beginning at line 11:

Current:

> Using GitHub code search (via the \texttt{gh} CLI, February--March 2026, with
> per-framework query sets and per-repository caps) we streamed each candidate
> repository through clone, extraction, and cleanup.

Replacement (supportable by the artifacts alone):

> Using GitHub code search (via the \texttt{gh} CLI, July 2026, with
> per-framework query sets and per-repository caps) we streamed each candidate
> repository through clone, extraction, and cleanup.

If a day-level statement is preferred, "in July 2026" may be replaced by
"on 11 July 2026" — both mining runs are bracketed to that date by the newest
pinned snapshot (2026-07-11T00:56Z) and the commits recording the outputs
(2026-07-11T15:15/19:01+01:00). Do not reuse the Feb--Mar dates anywhere in
the mining description; they belong only to the documentation-access notes in
`references.bib`.

(No paper files were edited; this report is the only file written.)
