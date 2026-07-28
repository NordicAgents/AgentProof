# Prospectively specified human-gate policy (HGP-1)

**Status:** fixed before case labeling. Written *before* any of the 32 candidate
workflows were assessed for gate presence, and before any comparison against the
`human_presence` or `human_gate_coverage` flag outputs.

**Purpose.** The three policy-violation cases currently reported on the 119-workflow
validation sample are produced by two *different* checks (the blunt `human_presence`
check and the path-sensitive `human_gate_coverage` check) applied to two different
artifact populations (mined graphs and reconstructed graphs). That is not a single
estimand. HGP-1 defines one operational procedure, applied uniformly and
independently to every workflow in the sample that contains a side-effecting tool at
*source* level, so that false negatives outside both flag universes are detectable.

**Unit of analysis.** One workflow = one mined source file (a `slug` in
`corpus/real_world/gt_triage_results.json`). The full audit denominator is
n = 119; this is not a population-prevalence denominator.

**Evidence base.** The workflow's actual source text under
`corpus/real_world/sources/<slug>.py`, or, if absent, the recorded `repo`/`sha`/`path`.
Extracted graphs (`corpus/real_world/graphs/`, `ground_truth/`) may be consulted as a
*navigation aid only*. A verdict must be justified by a source line, never by a graph
node kind, because the tool-to-llm kind error is precisely the failure under audit.

---

## (a) What counts as a side-effecting / irreversible tool

A **side-effecting tool** is a callable bound into the agent workflow (as a framework
tool, a function the agent may invoke, or a direct call inside a node body) whose
execution changes state outside the current process in a way that is not undone when
the process exits. It must fall into at least one category:

| Category | Definition | Positive examples |
|---|---|---|
| `destructive` | Deletes, drops, truncates, overwrites, or otherwise irreversibly removes existing persistent state. | `DROP TABLE`, `DELETE FROM`, `os.remove`, `shutil.rmtree`, `git reset --hard`, cache purge, resource teardown |
| `external_write` | Creates or mutates persistent state outside the process: databases, cloud storage, repositories, ticketing/CRM systems, files on the real filesystem. Non-idempotent HTTP `POST`/`PUT`/`PATCH`/`DELETE` to a third-party API. | `INSERT`/`UPDATE`/`MERGE`, `open(path,'w')` outside a temp dir, `bigquery.insert_rows`, `firestore.set`, `git commit`/`push`, GitHub issue/PR creation |
| `exec` | Executes attacker- or model-influenced code or commands. | `subprocess.run`, `os.system`, `exec`/`eval`, Python REPL tools (`PythonAstREPLTool`, `PythonCodeExecutionTool`), `kubectl apply`, container exec, `docker run` on a shared daemon |
| `financial` | Moves money or creates a financial obligation. | payment capture, transfer, trade order, invoice issue, refund, charge |
| `comms_third_party` | Delivers a message to a human or system **outside the operator's trust boundary**. | SMTP send, SendGrid/Gmail send, SMS, Slack/Discord post to a channel, social-media publish, outbound webhook to a customer |

**Decision rule.** Classification is by *what the callee actually does in source*, not by
its name. A tool named `save_report` that only mutates an in-memory dict is **not**
side-effecting; a tool named `helper` that shells out **is**.

## (b) What counts as a human gate

A **human gate** is a control point at which execution *blocks pending a human decision
that can prevent the side effect*. Exactly one of:

1. An explicit human checkpoint node: graph node of kind `HUMAN`; LangGraph
   `interrupt()`, `interrupt_before=[n]`, or `NodeInterrupt`; ADK
   `LongRunningFunctionTool` / tool-confirmation callback; CrewAI task with
   `human_input=True`.
2. An equivalent confirmation step in the node body: a blocking read of human input
   (`input()`, `click.confirm()`, a Streamlit/Gradio button handler, an awaited
   approval message) **whose negative outcome causes the side-effecting call to be
   skipped**. The negative branch must exist in source.
3. AutoGen `UserProxyAgent` with `human_input_mode="ALWAYS"` positioned in the
   conversation such that the human speaks between the proposing agent and the
   executing agent.

**Explicitly NOT a gate** (fixed before labeling, to avoid post-hoc leniency):

- A generic conversational REPL in which the human supplies the *task* and the agent
  then autonomously chooses and executes tools. The human authorises a goal, not the
  specific irreversible action.
- `human_input_mode="NEVER"` or `"TERMINATE"`.
- Logging, printing, or streaming the action to a human with no blocking decision.
- A post-hoc human review of output that occurs *after* the side effect has landed.
- A human gate that exists on some other branch but does not lie on the path to the
  side-effecting call.

## (c) Violation condition

> A workflow is a **violation** iff there exists at least one path from the workflow
> entry point to an invocation of a side-effecting tool (as defined in (a)) that
> contains no human gate (as defined in (b)).

Equivalently: the set of human gates does not *dominate* the side-effecting call site.
A gate on one branch does not discharge an ungated sibling branch. If any single
side-effecting tool is reachable ungated, the workflow is a violation, regardless of
how many other tools are correctly gated.

## (d) Exclusion rules

Excluded from the side-effecting set (these do **not** create a violation):

- **E1 Read-only tools.** Retrieval, search, `SELECT`, HTTP `GET`, vector-store query,
  file read, web scrape, `google_search`, Tavily, RAG lookup.
- **E2 Pure computation.** Arithmetic, parsing, formatting, string transforms.
- **E3 In-process state only.** Mutating a Python dict, agent/session state, LangGraph
  channel state, conversation history. Persisted state does not leave the process.
- **E4 LLM text generation.** An LLM node "writing" a report is text production, not an
  external write, unless the text is then persisted or transmitted by a separate call.
- **E5 Genuine mocks and stubs.** A tool whose body is a stub, fake, `MagicMock`, or
  hard-coded return with no real effect. The exclusion attaches to the *implementation*,
  not to the file's name or role.
- **E6 Constructively sandboxed side effects.** Writes confined to `tempfile`/`tmp_path`
  destroyed at process exit, or code execution inside a container created and torn down
  by the framework for that call. The confinement must be visible in source.

**Explicitly NOT excluded** (fixed before labeling):

- **N1 Demo, toy, tutorial, or example status.** If the code as written performs a real
  external write, execution, or send, it is side-effecting. "It's only a demo" is a
  statement about intent, not about behaviour. Intent is recorded separately in the
  `intent` field but does not change the verdict.
- **N2 Test files.** A file being a test does not exempt it. Exemption requires E5
  (the tool is actually a mock) or E6 (actually sandboxed).
- **N3 Unconfigured credentials.** A send/write that would fail for want of an API key
  still counts; the missing gate is the defect, not the missing key.
- **N4 Local filesystem writes** outside a temp directory. `open(f,'w')`, artifact dumps,
  and report files count as `external_write`.

## (e) Recording undecidable cases

Verdict domain is exactly `{violation, compliant, arguable, source_unavailable}`.

- `arguable` — the source is present but the policy cannot be applied mechanically to a
  determinate answer. Mandatory uses: (i) the side-effecting callee is imported from a
  module not present in the corpus and its behaviour cannot be established; (ii) tool
  dispatch is fully dynamic; (iii) a candidate gate exists but whether it dominates the
  call site depends on runtime configuration not fixed in source. An `arguable` verdict
  **must** state which of (i)–(iii) applies.
- `source_unavailable` — no source file and no retrievable `repo`/`sha`/`path` content.
- **An undecidable case is never recorded as `compliant`.** Silent downgrading of
  uncertainty to a negative is the specific bias this policy exists to prevent.

## Reporting rule

The headline audit proportion is `violation / 119`; any Wilson interval is
descriptive and has no design-based population coverage.
A **sensitivity band** is also reported: the lower bound counts only `violation`, the
upper bound counts `violation + arguable`. Both are reported regardless of whether the
resulting count is higher or lower than the 3 cases currently in the paper.

---

# Applied results (added after execution)

Machine-readable record: `corpus/real_world/human_gate_audit.json`.
Script: `scripts/human_gate_audit.py`. All 32 sources were read; none was dropped.
`Sidreyas__The_Grand_AI_Repo__builder` was missing from `corpus/real_world/sources/`
and was recovered from GitHub at the recorded sha `61bb48c6`, so there are **zero**
`source_unavailable` cases.

## Threshold rule applied under (a)

One clarification was needed at application time and was applied uniformly in both
directions: a side-effecting callable counts only if it is **agent/LLM-invocable** or
**called inside a graph node body that executes during a workflow run**. Script-level
setup, teardown, and reporting code is outside the (a) threshold. This is what
separates "binds an exec tool but never runs an agent" (compliant) from "the agent can
call it right now" (violation). It excludes some things that superficially look like
violations (`gallery_default.json` dumps in the two gallery builders, the eval CSV in
`project194`, `Cache.disk` in an autogen unit test) and it is the same rule that makes
the three autogen serialization tests compliant.

## Outcome

| Verdict | Count |
|---|---|
| `violation` | **12** |
| `compliant` | 9 |
| `arguable` | 11 |
| `source_unavailable` | 0 |

- Prevalence over the sample: **12/119 = 10.08%**, Wilson 95% **[5.86%, 16.80%]**.
- Sensitivity upper arm (`violation + arguable` = 23/119): [13.24%, 27.34%].
- Prevalence among the audited side-effecting workflows: 12/32 = 37.50% [22.93%, 54.75%].

This is a **fourfold upward revision** of the human-gate policy estimand, from 3/119
(2.52%) to 12/119 (10.08%). The previously reported figure is outside the new interval.

## False negatives

Three genuine violations lie outside **both** flag universes — neither
`human_presence` nor `human_gate_coverage` fires on them:

1. `Arhamirfan__Snake-Agents__snake_autogen`
2. `Itzkuldeep__AgentE-com__main`
3. `SAMAR-CODE404__backend__Main`

A further 9 violations are missed by the risk-aware check specifically (11 of the 12
have `human_gate_coverage_failed = false`); those 9 fall inside the `human_presence`
universe, but that universe contains 106 of 119 workflows and so carries almost no
information.

## Placebo gates (distinct failure mode)

Of the 32, **8 carry a human gate that cannot discharge the obligation**, and 5 of
those are outright placebos — a node typed `human` in the reference graph whose body
can never block execution:

| Slug | Nature of the gate |
|---|---|
| `SAMAR-CODE404__backend__Main` | placebo: 6 `*_human_approval` nodes whose body is `proceed = self.approval` against a constructor flag hard-set `True` |
| `Arhamirfan__Snake-Agents__snake_autogen` | placebo: `UserProxyAgent` with `human_input_mode="TERMINATE"` |
| `timleow__gym-kfc-daddies__cli_ui` | placebo: `get_user_prompt` is a task REPL, not an approval |
| `Sidreyas__The_Grand_AI_Repo__builder` | inert: `web_user_proxy` serialized into a config, never executed |
| `waqasniazi9__voice-agent__builder` | inert: `web_user_proxy` serialized into a config, never executed |
| `Itzkuldeep__AgentE-com__main` | non-dominating: real `ALWAYS` proxy, but ordered after the executing agent |
| `Sujas-Aggarwal__langraph-chatbot__v2.6.0` | partial: `confirmation_node` auto-confirms above a similarity threshold |
| `merdandt__SalesShortcut__websiter_creator_agent` | unverifiable: `request_URL` typed `human`, body absent |

**All 7** side-effecting workflows that both existing checks cleared were cleared
because the reference graph contained a node typed `human`. On source inspection,
**none of the 7 is a genuine dominating gate.**

This means the bias is not confined to the extractor. The source-reconstructed
reference graphs themselves overstate human oversight, because `human` is assigned from node
name or framework type rather than from whether the body can block. Any estimand
computed over those graphs — including the corrected, risk-aware one — is therefore
biased **downward**, and the direction of the bias is systematic rather than random.

The `human_detection` fidelity metric compounds this: for
`Arhamirfan__Snake-Agents__snake_autogen` and `Itzkuldeep__AgentE-com__main` it records
`tp = 1, recall = 1.0`, scoring the extractor as *perfectly* recovering human oversight
that does not exist. For `SAMAR-CODE404__backend__Main` it records `fn = 6` — the
extractor is penalised for failing to reproduce six placebo gates.

## Per-framework breakdown and post-stratification

Corpus mix (n=922): **LangGraph 400 / AutoGen 359 / CrewAI 113 / ADK 50** — the
mix the paper already uses and that `scripts/reviewer_analyses.py:57` hard-codes.

*Provenance, so this cannot drift again:* these counts come from the `framework`
field inside each graph JSON under `corpus/real_world/graphs/`, excluding the 8
`NordicAgents__AgentProof` self-repo files (930 − 8 = 922); verified independently
for this audit. The graph's own `framework` field is authoritative because the
extractor writes it from the file it actually parsed. Do **not** source the mix
from `scripts/matched_fidelity.py:251`, which labels v1 graphs using v2
(`metadata_v2.json`) records; 7 slug collisions resolve differently under v1
last-wins vs v2 first-wins, producing a spurious AutoGen 357 / CrewAI 115 split.
An earlier revision of this document used those wrong weights; the figures below
supersede it.

Estimator is the repository-clustered bootstrap within framework strata from
`scripts/reviewer_analyses.py`, **without** the finite-population correction: the
FPC presupposes SRSWOR from each stratum, and GitHub mining does not provide that.
Dropping it widens the intervals, which is the conservative direction.

| Framework | Violations / sampled | Rate | Corpus N | Weight |
|---|---|---|---|---|
| LangGraph | 6/40 | 15.0% | 400 | 0.434 |
| AutoGen | 5/35 | 14.3% | 359 | 0.389 |
| CrewAI | 0/20 | 0.0% | 113 | 0.123 |
| ADK | 1/24 | 4.2% | 50 | 0.054 |

- **Violations only:** post-stratified **12.30%**, repo-clustered bootstrap 95% **[4.74%, 21.20%]**.
- **Violations + arguable:** post-stratified **17.74%**, 95% **[9.50%, 27.03%]**.

The post-stratified point (12.30%) sits slightly *above* the raw sample rate
(10.08%) because the two heaviest strata, LangGraph and AutoGen, carry the highest
violation rates and together take 82% of the corpus weight. The single CrewAI
workflow in the audited set is `arguable`, so the CrewAI stratum contributes a
zero rate on n=20 — that stratum is the least well estimated.

## Composite estimand

The one confirmed structural defect is `gabrielpreda__adk-sql-agent__agent`
(`router_shape`, ADK). Under HGP-1 its policy verdict is **`arguable`, not
`violation`** — the SQL-executing sub-agents are imported from `subagents.*`,
none of which is in the corpus. It is therefore **not** among the 12, and the
union is a strict addition:

- **Composite = 13/119 = 10.92%**, Wilson 95% **[6.50%, 17.80%]**.
- Post-stratified **12.52%**, 95% **[5.01%, 21.41%]**.

## What happened to the three previously reported cases

The revision is **not** "3 plus 9 more". The old three came from two different
checks, and only one survives:

| Slug | Previous check | HGP-1 verdict |
|---|---|---|
| `Sujas-Aggarwal__langraph-chatbot__v2.6.0` | `human_gate_coverage` | **violation** (retained) |
| `Jamahl__fraya-25__crew` | `human_presence` | `arguable` (ii) |
| `Zen7-Labs__Zen7-Payment-Agent__agent` | `human_presence` | `arguable` (i) |

So HGP-1 retains 1 of the 3 and finds **11 new** violations. Both reclassified
cases are held at `arguable` only because their side-effecting callees live in
modules the mining pipeline never captured — in both the *absence of a gate is
certain*.

## Denominator caveat

> Only the 32 workflows that source review identified as containing
> side-effecting tools were assessed under the prospectively specified policy;
> the remaining 87 enter the denominator as non-violations through the upstream
> screen. An independent effect-signature sweep of all 87 surfaced 10
> candidates: 9 were screened correctly and 1 would be `arguable`. This reduces
> but does not eliminate screening error. Because annotation errors could also
> remove a current violation, 12/119 is an observed audit count, not a formal
> lower bound.

The screening was **the same procedure**, not a weaker one:
`gt_triage_results.json` holds one `classification` record per workflow for all
119, each with a `has_side_effecting_tools` boolean and a source-grounded `reason`
— a single pass over the whole sample, not a separate screen applied only to the
negatives. That is why the residual risk is small rather than large.

To bound it empirically rather than assert it, all 87 sources were swept for
side-effect signatures (subprocess/exec, SMTP/send, non-idempotent HTTP,
write-mode `open`, SQL DML/DDL, code executors, MCP workbenches). Ten files
matched and were re-read; nine are correctly screened (LLM inference calls
mistaken for third-party POSTs, sends to the operator's own UI, `tempfile`-confined
writes, script-level logging, read-only Redfish/fetch MCP toolsets, test fixtures),
and one — `MikhailMostWanted__Astra__mcp_session_host_example` — is borderline:
an `McpWorkbench` over a local example server with `/home` and `/tmp` roots, whose
server module is absent and whose demo tasks are read-only `ls` plus a booking
elicitation routed to a human elicitor. It would be `arguable` at worst.

Two residual error sources remain and are not zero: (1) a side-effecting tool
missed by the upstream classification, bounded above as small by the sweep; and
(2) two of the 87 have no source snapshot at all, so no sweep was possible
(`Sidreyas__The_Grand_AI_Repo__app_team_user_proxy`,
`Sidreyas__The_Grand_AI_Repo__test_society_of_mind_agent`).

## Honest limitations

- The 11 `arguable` cases are dominated by reason (i): the side-effecting callee lives
  in a module the mining pipeline never captured (single-file snapshots of multi-file
  packages). A repository-level corpus would resolve most of them, and several look
  likely to resolve toward `violation` — most notably
  `Zen7-Labs__Zen7-Payment-Agent__agent`, a crypto payment/settlement pipeline whose
  prompts forbid confirmation four separate times (L19, L22, L23, L94) and where only
  the callee body, not the missing gate, is unverifiable. They are held at `arguable`
  because the policy requires it, not because the evidence is balanced.
- The 87 workflows with no source-level side-effecting tool were not re-read
  under HGP-1, so any misclassification in that upstream step propagates. The
  reported 12/119 is therefore conditional on that screen.
- The audit is single-rater. `ed-donner__agents__sequential_agents` (prompt-level
  confirmation only) and `microsoft__ACV__test_cache_agent` (compliant) are the two
  calls most likely to move under a second rater.
