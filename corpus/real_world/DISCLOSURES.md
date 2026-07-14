# Responsible-disclosure tracking record

**Scope.** Four genuine defects surfaced by the base-rate study on public GitHub
agent workflows (paper section `03_realworld.tex`; hard gate 3.7 of the research
plan). This file is the internal tracking record. Per-repo maintainer drafts live
in `disclosures/<repo_slug>.md`.

**Status of this document (2026-07-13): DRAFTS ONLY.**
No issue has been filed, no email sent, no maintainer contacted. Every item below
is `drafted`. **Sending any of these requires the user's explicit go-ahead and a
real sender identity** to replace the `[SENDER]` placeholder in each draft (the
authors are anonymous during double-blind review; drafts say only "as part of an
academic study of agent-workflow verification" and carry no paper identification).

**Provenance basis.** Repository, pinned commit SHA, and file path come from
`metadata.json` / `metadata.lg_crew.json`. Line spans and quoted code were
re-verified by hand against the mined source snapshots in
`corpus/real_world/sources/<slug>.py`, which are byte-for-byte copies of each
file at the pinned SHA. Genuine-defect labels and their source-line-cited
justifications come from the adversarial triage passes
(`gt_triage_results.json` for the two reference-graph defects,
`wf_output_combined.json` / `validated_results.json` for the two
extractor-visible defects); every cited label is `real_defect` with the
independent verifier recording `agree = true`.

**The four defects at a glance.**

| ID | Repository | Stars | Defect class | Found by | Channel |
|----|-----------|-------|--------------|----------|---------|
| AP-RW-01 | Zen7-Labs/Zen7-Payment-Agent | 176 | Missing human gate on a financial (crypto-settlement) path | Extractor flag (`human_presence`) | **Private** GitHub security advisory, then public issue |
| AP-RW-02 | Jamahl/fraya-25 | 0 | Missing human gate before autonomous email-send / calendar-mutate | Extractor flag (`human_presence`) | Public GitHub issue |
| AP-RW-03 | Sujas-Aggarwal/langraph-chatbot | 0 | Unconstrained text-to-SQL executed on a superuser DB with no approval on any path | Reference-graph check (`human_gate_coverage`) | Public GitHub issue (mechanism, no weaponised payload) |
| AP-RW-04 | gabrielpreda/adk-sql-agent | 19 | Router mis-wiring: a "security router" that cannot terminate; unsafe requests fall through to SQL execution | Reference-graph check (`router_shape`) | Public GitHub issue |

**Timeline / ethics.** The paper's ethics statement commits to disclosing every
genuine defect to maintainers **before publication**. Planned order: send the two
extractor-visible drafts (AP-RW-01, AP-RW-02) and the two reference-graph drafts
(AP-RW-03, AP-RW-04) together, on the user's go-ahead, no later than the
camera-ready deadline. **No hard embargo is required** for AP-RW-02, AP-RW-03, or
AP-RW-04 (none is remotely exploitable by a third party against a deployed
service — see per-case assessment). AP-RW-01 gets a **private channel first** as a
courtesy, not because it is remotely exploitable, but because it moves real money
and is by far the most-watched repository (176 stars); we give the maintainer a
short good-faith window before any public mention.

---

## AP-RW-01 — Zen7-Labs/Zen7-Payment-Agent (missing human gate on a payment path)

- **Repository:** `Zen7-Labs/Zen7-Payment-Agent` (176 stars, framework: Google ADK)
- **Pinned SHA:** `a1546be076c14d1f270b1109c1e055fd53b685c8`
- **File:** `host_agent/agent.py`
- **Blob:** https://github.com/Zen7-Labs/Zen7-Payment-Agent/blob/a1546be076c14d1f270b1109c1e055fd53b685c8/host_agent/agent.py
- **Offending region:** lines **60–64** (`SequentialAgent("PaymentAgentPipeline",
  sub_agents=[payer_agent, settlement_agent, payee_agent])`) and lines **84–98**
  (root `Agent` whose live `instruction` at **line 94** reads
  *"Immediate make decision, tranfer to the target agent and automatical start
  the process, DO NOT make any confirmation."*).

**Defect class.** Missing human-in-the-loop (HITL) approval gate on a sensitive
(financial) action path. The pipeline chains payment **creation → settlement →
payee notification** with no interruption, and no ADK approval primitive
(`LongRunningFunctionTool`, a confirmation sub-agent, or a callback that escalates)
appears in the reviewed file.

**Concrete impact scenario.** A user (or a prompt-injected message that reaches the
host agent) that expresses payment intent triggers `PaymentAgentPipeline`, which
creates and then **immediately settles** an on-chain USDC/DAI payment. Crypto
settlement is irreversible; there is no confirm-before-settle step, and the live
host instruction actively tells the model not to ask for one. A wrong amount,
wrong payee, or injected instruction settles money with no chance for a human to
stop it.

**Evidence.**
- Artifact: `wf_output_combined.json` → triage entry
  `Zen7-Labs__Zen7-Payment-Agent__agent`, check `human_presence`,
  `final_label = real_defect`, `verified = true`, `agreed = true`; mirrored in
  `validated_results.json` `triage_details`.
- Verifier quote (verbatim): *"a genuine missing HITL gate on a sensitive
  crypto-payment path: SequentialAgent('PaymentAgentPipeline', sub_agents=[...])
  at lines 60-64 auto-chains payment creation -> settlement -> payee notification
  with no interruption, and the live host instruction (line 94 ...) says
  'automatical start the process, DO NOT make any confirmation.' The domain is
  irreversible USDC/DAI settlement, a sensitive action, so this is not the benign
  'no gate needed' intentional case."*
- **Honest caveats carried into the draft.** (1) The most emphatic
  "DO NOT CONFIRM" lines (source lines 19/22/23/29) sit inside a **commented-out**
  block (lines 9–57) and are dead documentation, *not* live behaviour; only the
  line-94 instruction is live. We cite only line 94. (2) The sub-agent modules
  (`payer_agent.py`, `settlement_agent.py`, `payee_agent.py`) were **not** in the
  study snapshot, so a gate implemented *inside* `settlement_agent` cannot be
  fully excluded from the file we reviewed. The independent verifier therefore
  rated confidence **medium**, not high. The draft states plainly that we reviewed
  only `host_agent/agent.py` and asks the maintainer to confirm whether a gate
  exists downstream.

**Proposed remediation (repair pattern: insert human-approval gate).** Add an
explicit approval step before settlement — e.g. a `LongRunningFunctionTool` /
confirmation sub-agent inserted between `payer_agent` and `settlement_agent` in the
`PaymentAgentPipeline`, and soften the line-94 instruction so it no longer forbids
confirmation on the money-movement path.

**Disclosure channel & justification.** **Private GitHub security advisory first**
(fall back to a maintainer email if advisories are disabled), then a public issue.
Rationale: the defect is a *design* safety gap, not a remotely triggerable
vulnerability (no third party reaches a deployed settlement endpoint here), so an
embargo is not strictly required; but the workflow moves real crypto and this is
the most-starred repo of the four, so a private heads-up with a short good-faith
window is the courteous and prudent choice.

**Status:** `drafted` (2026-07-13). Draft: `disclosures/Zen7-Labs__Zen7-Payment-Agent.md`.

| drafted | sent | acknowledged | fixed |
|---------|------|--------------|-------|
| 2026-07-13 | — | — | — |

---

## AP-RW-02 — Jamahl/fraya-25 (no human gate before autonomous email/calendar actions)

- **Repository:** `Jamahl/fraya-25` (0 stars, framework: CrewAI)
- **Pinned SHA:** `8da54c34951398cf66e0bba1144dfba40f240c3c`
- **File:** `crew.py`
- **Blob:** https://github.com/Jamahl/fraya-25/blob/8da54c34951398cf66e0bba1144dfba40f240c3c/crew.py
- **Offending region:** agents defined with `tools=mcp_tools` at lines **43** and
  **50**; tasks at lines **54–63** — **neither `Task` sets `human_input=True`**;
  crew assembled and run straight to completion at lines **65–72**
  (`crew.kickoff(email_json)`). Purpose declared in the module docstring at
  line **5** ("... action (e.g., booking meetings, drafting/sending replies)");
  operates on a hardcoded real individual (lines **30**, **36**).

**Defect class.** Missing human gate on a sensitive (external-communication +
calendar-mutation) path. CrewAI offers a per-task `human_input=True` review gate;
it is used on neither task.

**Concrete impact scenario.** An incoming email is processed autonomously by a
two-task crew whose agents both hold Composio **Gmail + Google Calendar** MCP tools
(loaded at lines 108–109), including message-send and calendar write/delete
capability. Without a `human_input` gate, a reply can be **sent** — and a meeting
rescheduled or cancelled — on a real person's live account with no human seeing it
first. A misread intent or an adversarial inbound email turns directly into an
outbound action.

**Evidence.**
- Artifact: `wf_output_combined.json` → triage entry `Jamahl__fraya-25__crew`,
  check `human_presence`, `final_label = real_defect`, `verified = true`,
  `agreed = true`, confidence `medium`.
- Verifier quote (verbatim): *"Neither Task sets human_input=True (analyze_task
  lines 54-58, reply_task lines 59-63); the crew is a plain sequential pipeline run
  straight to completion via crew.kickoff (lines 65-72) with no approval node. ...
  Autonomous send/mutate with no approval gate is exactly the
  sensitive-path-bypasses-human-review pattern."*
- **Honest caveats carried into the draft.** Confidence is **medium**: the
  `reply_agent` goal is *"Draft email replies"* (line 48) and `reply_task`'s
  `expected_output` is *"Drafted reply"* (line 61), which admits a benign
  **draft-only** reading where a human sends outside the graph. The
  module-level `delete_calendar_event` / `reschedule_calendar_event` functions
  (lines 87–97) are **dead code** — never registered as tools — so the real
  mutate capability comes from the MCP calendar tools, not those functions. The
  draft is framed as a robustness suggestion, not an alarm, and explicitly asks
  whether a send/mutate step ever runs unattended.

**Proposed remediation (repair pattern: insert human-approval gate).** Set
`human_input=True` on `reply_task` (and any task that can send email or mutate the
calendar), or route send/mutate through an explicit approval step, so a human
confirms before the crew acts on a live account.

**Disclosure channel & justification.** **Public GitHub issue.** Example-grade
personal project (0 stars), not exploitable by any third party; a courteous public
issue framed as a safety suggestion is appropriate and no embargo is needed.

**Status:** `drafted` (2026-07-13). Draft: `disclosures/Jamahl__fraya-25.md`.

| drafted | sent | acknowledged | fixed |
|---------|------|--------------|-------|
| 2026-07-13 | — | — | — |

---

## AP-RW-03 — Sujas-Aggarwal/langraph-chatbot (ungated text-to-SQL on a superuser DB)

- **Repository:** `Sujas-Aggarwal/langraph-chatbot` (0 stars, framework: LangGraph)
- **Pinned SHA:** `1e5cc6bd1ea8875de5058289fab6d3ad71138a5a`
- **File:** `versions/v2.6.0.py`
- **Blob:** https://github.com/Sujas-Aggarwal/langraph-chatbot/blob/1e5cc6bd1ea8875de5058289fab6d3ad71138a5a/versions/v2.6.0.py
- **Offending region:** router `route_after_spell_check` lines **492–496** (skips
  `confirmation` whenever `needs_confirmation` is false); graph edges
  `generate_sql → execute_query → END` lines **519–520**; `execute_query_node`
  lines **459–472**; the SQL sink `PostgreSQLManager.execute_query` lines
  **166–174** (runs *any* statement, no SELECT-only restriction, no commit-gating
  that would help); generation prompt embeds the raw `user_query` at lines
  **419–432**; `confirmation` node lines **384–397** confirms **only location
  spelling**, never the SQL; superuser DSN at line **674**
  (`postgresql://postgres:admin@localhost:5432/...`).

**Defect class.** A sensitive tool (arbitrary SQL execution) is reachable with no
human gate and no read-only enforcement on **any** path. Detected on the
reconstructed reference graph by the `human_gate_coverage` check — the AST
extractor missed the binding (`tool→llm` kind error), which is exactly the
false-negative story the paper documents.

**Concrete impact scenario.** For a high-confidence location spelling match
(`similarity ≥ 0.6`, line 272 sets `needs_confirmation` false), the router routes
straight to `generate_sql`, which builds SQL from the **raw user query** and runs
it verbatim through a **superuser** Postgres connection. The one confirmation node
only asks "did you mean this village?" — it never shows or approves the SQL. A user
request (or prompt injection) that steers generation toward a destructive or
side-effecting statement executes with no review; the superuser DSN means
side-channels beyond plain DML are in reach.

**Evidence.**
- Artifact: `gt_triage_results.json` → `triage[4]`, slug
  `Sujas-Aggarwal__langraph-chatbot__v2.6.0`, check `human_gate_coverage`,
  `primary.label = real_defect` (confidence high), `verify.agree = true`,
  `verify.final_label = real_defect`.
- Verifier quote (verbatim): *"no code path ever reviews the SQL. The sink is
  genuinely dangerous: execute_query (166-174) has no SELECT-only restriction on a
  hardcoded superuser connection (line 674), and the generation prompt (419-432,
  439) embeds raw user_query with no read-only constraint. ... Unreviewed superuser
  text-to-SQL execution is a gap a developer would fix."*
- Note preserved from the verifier: `execute_query` (166–174) never `commit()`s, so
  plain DML happens to roll back on close — this is **accidental, not a safeguard**;
  superuser side-channels survive it. The draft does not rely on the roll-back
  being a protection.

**Proposed remediation (repair pattern: insert human-approval gate + least
privilege).** (1) Show the generated SQL and require explicit human approval before
`execute_query` on every path (not only the spelling-confirmation path). (2) Connect
with a **read-only** role and restrict to `SELECT` (allowlist / parse-and-reject
non-SELECT). The two together close the gap; either alone is weaker.

**Disclosure channel & justification.** **Public GitHub issue**, written with the
**mechanism only and no weaponised payload**. Assessment of third-party
exploitability: the repo as published is a personal CLI demo pointed at
`localhost` with hardcoded demo credentials — there is no deployed, third-party
reachable service, so no embargo is required. The risk becomes real only if the
owner deploys it and exposes the query box to untrusted users; the issue notes that
and suggests the fixes above. We deliberately avoid posting a copy-paste
destructive statement.

**Status:** `drafted` (2026-07-13). Draft: `disclosures/Sujas-Aggarwal__langraph-chatbot.md`.

| drafted | sent | acknowledged | fixed |
|---------|------|--------------|-------|
| 2026-07-13 | — | — | — |

---

## AP-RW-04 — gabrielpreda/adk-sql-agent (security router that cannot route)

- **Repository:** `gabrielpreda/adk-sql-agent` (19 stars, framework: Google ADK)
- **Pinned SHA:** `ef9206ea3d5c4a89b956481043a1508ff433a0fc`
- **File:** `sql_agent/agent.py`
- **Blob:** https://github.com/gabrielpreda/adk-sql-agent/blob/ef9206ea3d5c4a89b956481043a1508ff433a0fc/sql_agent/agent.py
- **Offending region:** `security_router_agent` lines **95–101** — a plain
  `LlmAgent` with **no tools, callbacks, or escalation mechanism**, despite its
  name, description (line 98: *"exits on not secure, continues on secure"*), and
  instruction (lines 73–87: *"NOT SECURE → ... system exits"*); embedded in the
  root `SequentialAgent` lines **134–142**, which runs **all** sub-agents
  unconditionally; the developer's own comment at lines **130–132** concedes the
  fall-through (*"all agents execute in sequence ... the refinement loop will
  receive that as input and should handle it gracefully"*). The refinement loop
  that generates/executes SQL is lines **107–117**.

**Defect class.** Router mis-wiring: a control-flow node declared as a security
gate cannot actually gate control flow, so the safety check is inert. Detected on
the reconstructed reference graph by `router_shape` (the router has a single
unconditional outgoing edge).

**Concrete impact scenario.** A request the safety agent flags **NOT SECURE**
(e.g. `DROP TABLE`, `DELETE FROM`, `TRUNCATE`) is *not* stopped: because
`SequentialAgent` runs every sub-agent in order regardless of any "final rejection"
text, control falls through to the refinement loop that rewrites, generates, and
executes SQL. The security layer the repo advertises does nothing; unsafe queries
proceed to generation/execution.

**Evidence.**
- Artifact: `gt_triage_results.json` → `triage[6]`, slug
  `gabrielpreda__adk-sql-agent__agent`, check `router_shape`,
  `primary.label = real_defect` (confidence high), `verify.agree = true`,
  `verify.final_label = real_defect`.
- Verifier quote (verbatim): *"security_router_agent (agent.py lines 95-101) is
  declared a security router by name, description ... and instruction ..., yet it is
  a plain LlmAgent with no tools, callbacks, or escalation, inside a SequentialAgent
  (lines 134-142) that unconditionally runs the refinement_loop ... after any
  rejection."*
- Corroboration cited by the verifier and carried into the draft: the sibling file
  `sql_agent/agent_v2.py` (same SHA) defines `loop_termination_callback`
  (lines **16–19**) that only **logs** and is never wired to `end_invocation` /
  `escalate` — evidence the author intended an exit mechanism but did not implement
  one. (This strengthens the "unfinished control, not intentional design" reading.)

**Proposed remediation (repair pattern: fix router wiring).** Give the security
step real terminating power: implement it with a callback that calls
`tool_context.actions.escalate` / `end_invocation` (or `transfer_to_agent`) on
NOT-SECURE, or restructure so the router conditionally gates entry to the
refinement loop instead of sitting in an unconditional `SequentialAgent`. Prompt
text alone ("this is the END") cannot stop a `SequentialAgent`.

**Disclosure channel & justification.** **Public GitHub issue.** This is a
robustness bug — an advertised safety control that is a no-op — in example code
(19 stars); it is not a remotely exploitable vulnerability against a third party, so
no embargo is needed. A public issue lets other users of the example learn the
security step needs real wiring.

**Status:** `drafted` (2026-07-13). Draft: `disclosures/gabrielpreda__adk-sql-agent.md`.

| drafted | sent | acknowledged | fixed |
|---------|------|--------------|-------|
| 2026-07-13 | — | — | — |

---

## Send-readiness sanity check

Each draft is written to be **verifiable by a maintainer in under five minutes from
the cited SHA alone**: every claim cites `file @ SHA` plus a specific line span that
matches the code at that commit (re-checked by hand against the mined snapshots,
which are byte-for-byte copies of the pinned blobs). None of the drafts depends on
running the code, on our extractor, or on the paper.

**Blockers to sending (all four):**
1. **User go-ahead required.** Nothing is sent without the user's explicit
   instruction.
2. **Sender identity required.** Each draft carries a `[SENDER]` placeholder to be
   replaced at send time; drafts must remain paper-anonymous until acceptance
   (double-blind), so they say only "an academic study of agent-workflow
   verification" and name no venue.
3. **AP-RW-01 channel setup.** Confirm whether the Zen7 repo has GitHub Security
   Advisories enabled; if not, use the maintainer email/contact for the private
   first-notice.

**Not confirmable / caveats to flag to the reader:**
- **AP-RW-01 (Zen7):** sub-agent files were not in the study snapshot, so a gate
  inside `settlement_agent` cannot be excluded from our review — the draft says so
  and asks the maintainer. Independent-verifier confidence is **medium**.
- **AP-RW-02 (fraya-25):** a benign **draft-only** reading is plausible;
  independent-verifier confidence is **medium**. Draft is framed as a suggestion,
  not a vulnerability claim.
- **AP-RW-03 / AP-RW-04:** both `real_defect`, high confidence, both verifiers
  agreed; both fully reproducible from the single cited file at the pinned SHA.
</content>
</invoke>
