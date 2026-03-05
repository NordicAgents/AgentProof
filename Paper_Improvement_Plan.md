# Strengthening Plan: "Static Graph Verification for Agent Workflow Safety"

## Purpose

This document provides a structured, actionable plan for addressing each issue raised during the professor-level review, organized by priority. Follow this plan before submitting to a high-impact venue (ICSE, FSE, ASE, USENIX Security, S&P, or similar).

---

## Priority 1: Critical Issues (Must Fix Before Submission)

### 1.1 Replace Self-Constructed Corpus with Real-World Workflows

**Problem:** All 18 workflows are author-constructed, making the 55% defect rate empirically meaningless. Reviewers will question whether defects were introduced intentionally.

**Action Items:**

- **Mine GitHub repositories directly.** Search GitHub for repos using LangGraph, CrewAI, AutoGen, and Google ADK. Use queries like `language:Python "StateGraph"` (LangGraph), `language:Python "Crew("` (CrewAI), `language:Python "RoundRobinGroupChat"` (AutoGen), and `language:Python "SequentialAgent"` (ADK).
- **Target 80–150 real workflows** across the four frameworks. Even if many are small or trivial, the sheer count provides statistical power.
- **Automate extraction at scale.** Build a pipeline that clones repos, runs your extractors, and logs success/failure/error. Report extraction success rate as a metric (e.g., "We attempted extraction on 200 repositories and successfully extracted 142 workflows").
- **Classify defects independently.** Have two authors independently label each flagged defect as true positive or false positive. Report inter-annotator agreement (Cohen's kappa).
- **Preserve your current 18 workflows as a "curated benchmark"** but clearly label them as illustrative examples, not the primary evaluation.

**Where to update in the paper:**
- Section 7.1: Replace corpus description with real-world mining methodology.
- Section 7.2: Report defect rates on real workflows.
- Add a new subsection (e.g., 7.1.1) describing the mining and filtering methodology.

**Expected timeline:** 3–5 weeks for mining, extraction, and labeling.

---

### 1.2 Reframe the Contribution Away from Algorithm Novelty

**Problem:** The five structural checks are textbook graph algorithms (BFS, DFS, degree checks). Reviewers at top venues will not find them technically novel.

**Action Items:**

- **Shift the narrative in Section 1 (Introduction) and Section 6.1.** The contribution is not the algorithms — it is:
  1. The observation that agent frameworks expose analyzable graph structure.
  2. The unified extraction model that bridges four heterogeneous frameworks.
  3. The empirical evidence that real workflows contain these bugs.
  4. The integration into a practical pre-deployment verification pipeline.
- **Rewrite the contributions list** to emphasize the system and the empirical findings over the checks themselves.
- **Downplay the soundness proofs.** Move the proofs to the appendix (they already are) but also reduce how much emphasis the main text places on them. Stating "soundness follows directly from BFS correctness" in one sentence is more appropriate than a full lemma for ExitReach.
- **Emphasize the extraction challenge.** Expand Section 5.2 to include concrete code examples showing how each framework represents workflows differently, and why a unified model is non-trivial. Show a side-by-side comparison of LangGraph code vs. CrewAI code for the same logical workflow.

**Where to update in the paper:**
- Section 1 (Contributions list): Rewrite.
- Section 5.2: Expand with code examples and a comparison table.
- Section 6.1: Shorten, de-emphasize algorithmic detail.
- Appendix A: Keep proofs but add a one-line note that they follow standard results.

---

### 1.3 Evaluate the Temporal DSL on Real Policies and Violations

**Problem:** The temporal DSL is presented but never evaluated on real policy violations. No policies are shown being written, violated, or satisfied.

**Action Items:**

- **Define 10–15 concrete temporal policies** motivated by real safety requirements. Examples:
  - `G !tool:delete_production_db` — never invoke the production database deletion tool.
  - `tool:draft_email -> F tool:human_review` — every email draft must be followed by human review before the next draft.
  - `tool:fetch_pii -> F[<=3] tool:anonymize` — after fetching PII, anonymization must occur within 3 steps.
  - `(tool:sql_query -> F tool:review) AND (G !tool:drop_table)` — conjunction of a response and a forbidden pattern.
- **Generate execution traces** from your real-world corpus (or simulate them based on the extracted graphs) and evaluate each policy.
- **Report a policy violation matrix:** For each workflow × policy pair, report pass/fail/not-applicable.
- **Show at least 2–3 detailed case studies** where a temporal policy catches a meaningful violation with a concrete witness trace.
- **Justify the DSL scope empirically.** After defining your 10–15 policies, show what fraction fall within your seven expression forms vs. what would require full LTL. If 90%+ of practical policies fit your fragment, that is a strong justification for the design choice.

**Where to update in the paper:**
- Section 6.2: Add a table of example policies with natural-language motivation.
- Section 7: Add a new subsection (e.g., 7.3) for temporal policy evaluation.
- Section 9: Update the limitation about DSL expressiveness with your empirical coverage data.

**Expected timeline:** 1–2 weeks.

---

### 1.4 Sharpen the Threat Model for T2 (Malicious Injection)

**Problem:** If an adversary can modify workflow definitions, they may also be able to disable verification. The paper does not specify the deployment model under which T2 guarantees hold.

**Action Items:**

- **Define a concrete deployment architecture** where static verification is enforced. Example: a CI/CD pipeline where verification runs as a mandatory gate in a trusted build system, and workflow definitions are checked into version control with code review.
- **Distinguish the trust assumptions** for T1 vs. T2 explicitly:
  - T1: Developer is trusted but fallible. Verification catches unintentional errors.
  - T2: Adversary can modify workflow files but cannot modify the CI/CD pipeline or the verification tool itself. This is analogous to how linters catch malicious code contributions in open-source projects — the linter is trusted, the contribution is not.
- **Discuss what T2 does NOT cover:** An adversary who compromises the build system, the extractor, or the verification tool itself. This is standard in security papers — clearly scoping the threat model strengthens it.
- **Add a deployment diagram** showing where Agentproof sits in a CI/CD pipeline and what is inside vs. outside the trust boundary.

**Where to update in the paper:**
- Section 2: Rewrite T2 discussion with deployment model.
- Add a figure (e.g., Figure 1b) showing the CI/CD integration.

---

## Priority 2: Moderate Issues (Strongly Recommended)

### 2.1 Add Comparison with Existing Model Checkers

**Problem:** SPIN, NuSMV, and CBMC are cited but never compared against experimentally or even qualitatively in depth.

**Action Items:**

- **Write a qualitative comparison table** (new Table, e.g., Table 7) with columns: Tool, Input format, Property language, Modeling effort, Verification time, Domain-specific support. Include SPIN, NuSMV, CBMC, and Agentproof.
- **Demonstrate the modeling effort gap.** Take one of your workflows and show the Promela (SPIN) or SMV (NuSMV) model that would be needed to check the same properties. This concretely shows that existing tools require manual modeling while Agentproof extracts the model automatically.
- **Optionally, run SPIN on 2–3 examples** and compare verification time. This is likely overkill (SPIN is designed for much harder problems), but it concretely shows that general-purpose model checkers are not well-suited to this specific domain.

**Where to update in the paper:**
- Section 8.2: Expand with the comparison table and modeling effort example.
- Section 7: Optionally add a subsection comparing against SPIN.

---

### 2.2 Validate Extractors on Real-World Code (Not Just Test Cases)

**Problem:** Extractor accuracy is evaluated on 4–8 author-written test cases per framework, which is circular.

**Action Items:**

- **Use the real-world corpus from Priority 1.1.** For a random sample of 20–30 extracted workflows, manually inspect the extracted AgentGraph against the source code and annotate correctness.
- **Report per-framework metrics:** Node detection precision/recall, node-kind classification accuracy, edge detection precision/recall.
- **Identify and categorize extraction failures.** Common failure modes might include:
  - Dynamic graph construction (e.g., nodes added in a loop).
  - Custom node types not recognized by heuristics.
  - Framework version incompatibilities.
- **Quantify the human-node detection limitation.** On how many real workflows does the naming heuristic fail? Propose alternatives (e.g., detecting `input()` calls or `interrupt_before`/`interrupt_after` in LangGraph).

**Where to update in the paper:**
- Section 7.5: Replace with real-world extractor evaluation.

---

### 2.3 Separate Structural Defects from Policy Violations in Reporting

**Problem:** "Missing human gate" (10/15 defects) is a configurable policy check, not a structural bug. Lumping them together inflates the defect rate.

**Action Items:**

- **Report two distinct defect categories:**
  - **Structural defects** (topology bugs): dead-end nodes, unreachable exits, router shape violations, missing tool declarations. These are bugs regardless of policy.
  - **Policy violations** (configurable checks): missing human gate. These depend on the operational context.
- **Present two defect rates:**
  - Structural defect rate: X% of workflows (currently 4/18 ≈ 22% based on the author-constructed corpus; re-measure on the real corpus).
  - Policy violation rate when `require_human=True`: Y% of workflows.
- **Update Table 4** to have a "Category" column distinguishing these.
- **Discuss in the text** that the human gate check is context-dependent: it is critical in regulated domains (healthcare, finance) but may be unnecessary for internal tooling.

**Where to update in the paper:**
- Section 7.2: Split the results and discussion.
- Table 4: Add category column.
- Abstract: Revise the "55%" claim to be more precise.

---

### 2.4 Add False Positive Analysis

**Problem:** The paper assumes all flagged defects are true positives. In practice, some "dead ends" or "missing gates" might be intentional.

**Action Items:**

- **For each defect found in your real-world corpus**, classify it as:
  - **True positive (TP):** A genuine bug or unintended behavior.
  - **False positive (FP):** An intentional design choice flagged incorrectly.
  - **Arguable:** Could be either depending on context.
- **Report precision** = TP / (TP + FP) for each check type.
- **Discuss common false positive patterns:**
  - Dead-end nodes that are intentional error-halting states.
  - Missing human gates in low-risk or internal-only workflows.
  - Router nodes with non-conditional edges that are used as dispatchers (not true routers).
- **Propose mitigations** for false positives: annotation-based suppression (e.g., `# agentproof: ignore dead-end` comments), severity tiers, or configuration profiles.

**Where to update in the paper:**
- Section 7.2: Add a false positive analysis subsection.
- Section 9: Mention annotation-based suppression as future work.

---

## Priority 3: Minor Issues (Improve Before Final Submission)

### 3.1 Add an End-to-End Running Example

**Action:** Create a single example that appears in Section 1 (motivation), Section 5 (extraction showing real framework code → AgentGraph), Section 6 (check failure + witness trace), and Section 6.2 (temporal policy evaluated on a trace from this workflow). Thread it throughout the paper so the reader follows one coherent story.

### 3.2 Improve Abstract and Introduction Structure

**Action:**
- Abstract: Lead with the problem and insight (1–2 sentences), then the approach (1–2 sentences), then the key result (1 sentence), then scope (1 sentence). Move the laundry list of specifics (five checks, four frameworks, 18 workflows) to the contributions paragraph.
- Introduction: Shorten the motivating example slightly and move to the key insight faster: "When agent behavior is graph-structured, safety properties reduce to graph reachability and temporal constraints."

### 3.3 Improve Related Work Narrative

**Action:** Restructure Section 8 to tell a story: "Runtime tools (8.1) catch content-level violations but miss structural ones. Static analysis tools (8.2) could theoretically be applied but require manual modeling. Temporal monitoring (8.3) is well-studied but not applied to agent workflows. Agent safety research (8.4) focuses on alignment, not orchestration. Our work fills the gap between runtime content checking and structural verification."

### 3.4 Address the Scalability Gap

**Action:** Add one paragraph in Section 7.3 acknowledging that real workflows are small (5–12 nodes) and that the scalability experiment demonstrates ceiling-freeness rather than practical necessity. Optionally, argue that as agent systems grow (multi-agent compositions, hierarchical subgraphs), larger graphs will become common.

### 3.5 Refine the Title

**Options to consider:**
- "Agentproof: Static Verification of Agent Workflow Graphs" (more precise, names the tool)
- "Catching Structural Defects in Agent Workflows Before Deployment" (more descriptive)
- "Pre-Deployment Verification of Agent Orchestration Graphs" (emphasizes timing)
- Keep the current title if the venue audience interprets "safety" in the systems/verification sense rather than the AI alignment sense.

### 3.6 Add Reproducibility and Artifact Details

**Action:**
- Open-source the tool and corpus on GitHub before submission.
- Add a "Data Availability" or "Artifact" section stating the URL.
- If the venue supports artifact evaluation (e.g., ICSE, FSE), prepare for an artifact evaluation badge submission.

---

## Recommended Venue Strategy

| Venue | Fit | Key Requirement |
|-------|-----|-----------------|
| ICSE (SE track) | Strong | Needs real-world evaluation, artifact |
| FSE | Strong | Needs empirical rigor, tool maturity |
| ASE | Strong | Tool papers welcome, needs comparison |
| ISSTA | Moderate | Testing/analysis focus, needs deeper formal treatment |
| USENIX Security | Moderate | Needs stronger adversarial evaluation (T2) |
| AAMAS | Moderate | Agent-focused, but less emphasis on SE rigor |
| NeurIPS (SafeGenAI workshop) | Moderate | Shorter format, less empirical pressure |

**Recommended primary targets:** ICSE or FSE, as the work is fundamentally a software engineering contribution (static analysis of software artifacts) applied to the agent domain.

---

## Revision Timeline (Estimated)

| Week | Task |
|------|------|
| 1–2 | Build GitHub mining pipeline; begin extracting real-world workflows |
| 2–3 | Run extractors on mined repos; manually validate a sample of 30 |
| 3–4 | Run all checks on real corpus; classify TPs and FPs; compute metrics |
| 4–5 | Define temporal policies; evaluate on traces; write case studies |
| 5–6 | Rewrite Sections 1, 2, 5.2, 7; add comparison table with SPIN/NuSMV |
| 6–7 | Revise abstract, related work, title; prepare artifact for open-source release |
| 7–8 | Internal review round; polish; submit |

---

## Checklist Before Submission

- [ ] Real-world corpus of 80+ workflows mined from GitHub
- [ ] Defect rates reported separately for structural bugs vs. policy violations
- [ ] False positive analysis with per-check precision
- [ ] Temporal DSL evaluated on 10+ concrete policies with violation case studies
- [ ] Threat model T2 includes deployment architecture diagram
- [ ] Extractor accuracy validated on real-world code (not just test cases)
- [ ] Comparison table with SPIN/NuSMV/CBMC (at minimum qualitative)
- [ ] End-to-end running example threaded through the paper
- [ ] Abstract revised to lead with problem/insight, not a list of numbers
- [ ] Related work restructured as narrative
- [ ] Tool and corpus open-sourced with URL in paper
- [ ] Co-authors have reviewed the full revised draft
