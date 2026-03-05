# Agentproof — Research Paper Improvement Plan

## Paper Goal

Publish Agentproof in a high-impact venue (target: USENIX Security, IEEE S&P, CCS, ICSE, or a strong AI safety workshop as a stepping stone).

---

## Current Paper Diagnosis

The paper introduces static verification of agent workflow graphs — a timely and underexplored idea. However, it currently reads as a tool report rather than a research contribution. The gaps fall into five areas: formalization, evaluation, related work, expressiveness of the temporal DSL, and extractor trustworthiness.

---

## Phase 1 — Foundation (Weeks 1–3)

### 1.1 Define a Formal Threat Model

- Clearly state **who** you are protecting against: developer mistakes, malicious workflow injection, runtime graph mutation, or all three.
- Define the trust boundary: what is assumed correct (the framework API, the extractor, the LLM behavior) and what is verified.
- Write a dedicated "Threat Model" section (half a page) placed right after the introduction.

### 1.2 Formalize the Graph Model

- Give a proper mathematical definition of AgentGraph as a labeled directed graph $G = (V, E, \kappa_V, \kappa_E, T, v_0, V_f)$ where $\kappa_V$ and $\kappa_E$ are kind-labeling functions, $T$ maps tool nodes to tool-name sets, $v_0$ is the entry, and $V_f$ is the exit set.
- Define what constitutes a **valid execution trace** over this graph (a sequence of nodes consistent with edge transitions).
- Define each structural property (reachability, dead-end, isolation, router shape) as a formal predicate over $G$.

### 1.3 Prove Soundness

- For each structural check, state and prove a soundness lemma: "If the check passes, then property $P$ holds for all valid execution traces of $G$."
- These proofs will be short (most are straightforward graph-theoretic arguments), but their presence is what separates a research paper from a tool demo.

**Deliverable:** Rewritten Sections 4 and 5 with formal definitions, a new Threat Model section, and a short appendix with soundness proofs.

---

## Phase 2 — Strengthen the Temporal DSL (Weeks 3–5)

### 2.1 Expand Expressiveness

The current DSL supports only three fixed patterns. Expand to cover at least the **safety fragment of LTL** (Boolean combinations of G, F, U over atomic propositions). Specifically, add support for:

- Conjunction and disjunction of rules: `(G !a) AND (b -> F c)`
- Bounded temporal operators: `a -> F[<=k] b` (b must occur within k steps after a)
- Nested until: `a U (b U c)`
- Response chains: `a -> F b -> F c` (a triggers a required sequence)

### 2.2 Justify the Fragment Empirically

- Survey 20–30 real safety policies from agent safety blog posts, guardrail documentation (NeMo Guardrails, Guardrails AI, LlamaGuard), and enterprise deployment guides.
- Classify each policy into the temporal pattern it requires.
- Report what percentage of real-world policies your (expanded) DSL can express. This is a strong empirical argument for the design choice.

### 2.3 Improve Compilation

- If you expand beyond three-state DFAs, describe the compilation algorithm properly (e.g., standard LTL-to-Büchi-to-DFA pipeline or a direct construction for the safety fragment).
- Report DFA state counts for the expanded rule set.

**Deliverable:** Rewritten Section 5.2 with expanded DSL grammar, compilation algorithm, and a table classifying real-world policies by pattern.

---

## Phase 3 — Evaluation Overhaul (Weeks 5–9)

This is the most critical phase. The current evaluation uses three small author-constructed graphs. A high-impact paper needs real-world evidence.

### 3.1 Real-World Workflow Corpus

- Scrape open-source repositories using LangGraph, CrewAI, AutoGen, and Google ADK from GitHub. Search for files containing `StateGraph`, `Crew`, `GroupChat`, `SequentialAgent`, etc.
- Target at least **15–20 real workflows** of varying complexity.
- Extract AgentGraphs from all of them and report statistics (node/edge counts, node-kind distributions, presence of human gates, etc.).
- This corpus becomes a reusable artifact for the community.

### 3.2 Bug/Defect Study

- Run all structural checks on the real-world corpus.
- Report how many workflows have defects: unreachable nodes, dead ends, missing human gates, undeclared tools.
- Categorize the defects by severity and type.
- This is the most compelling part of the evaluation — showing that real agent workflows have real bugs that Agentproof catches.

### 3.3 Scalability Experiments

- Generate synthetic graphs at scale: 50, 100, 500, 1000, 5000 nodes with realistic edge densities.
- Measure extraction time, structural check time, and temporal monitor compilation/evaluation time.
- Plot scaling curves. Show that the approach remains practical at production scale.

### 3.4 Comparison with Runtime Guardrails

- Pick one or two runtime guardrail tools (e.g., NeMo Guardrails, Guardrails AI).
- Construct scenarios where:
  - Agentproof catches a defect statically that the runtime tool cannot (e.g., unreachable exit, missing human gate in a branch that hasn't been triggered yet).
  - The runtime tool catches something Agentproof cannot (e.g., toxic LLM output).
- Present a qualitative comparison table showing the complementary strengths.

### 3.5 Extractor Accuracy

- For at least 10 real workflows, manually annotate the ground-truth graph (node kinds, edge kinds).
- Run the extractor and compute precision/recall for node-kind classification and edge detection.
- Report and discuss failure cases (e.g., human gates identified only by naming heuristic).

**Deliverable:** Rewritten Section 6 with five subsections (corpus stats, defect study, scalability, comparison, extractor accuracy), supported by 4–6 tables/figures.

---

## Phase 4 — Related Work Expansion (Weeks 9–10)

### 4.1 Structure the Section

Organize related work into four subsections:

1. **Runtime agent safety tools:** NeMo Guardrails, Guardrails AI, LlamaGuard, Rebuff, tool-call interceptors, prompt injection defenses. Discuss what they catch and what they miss structurally.
2. **Static analysis and model checking in software engineering:** SPIN, NuSMV, CBMC, abstract interpretation, dataflow analysis. Position Agentproof relative to classical verification — what is new about applying these ideas to agent graphs specifically?
3. **Temporal logic monitoring:** Runtime verification (RV) community — Havelund & Rosu (JavaMOP), Bauer et al. (LTL monitoring), Barringer et al. Distinguish Agentproof's lightweight approach from full RV frameworks.
4. **Agent architecture and safety taxonomies:** Recent work on agent safety (e.g., from Anthropic, DeepMind, OpenAI), multi-agent coordination safety, tool-use risk frameworks.

### 4.2 Positioning Statements

For each category, write 2–3 sentences explicitly stating how Agentproof differs. Avoid vague "complementary" claims — be precise about what you do that they cannot and vice versa.

**Deliverable:** 1.5–2 page related work section replacing the current single paragraph.

---

## Phase 5 — Writing and Presentation (Weeks 10–12)

### 5.1 Tone and Framing

- Remove all repository/README-style language ("in this repository we include," "the implementation," etc.). Write as a research paper, not a project description.
- State the "non-goal" about LLM output semantics once in the introduction and once briefly in limitations. Do not repeat it elsewhere.
- Strengthen the introduction with a motivating example: show a concrete agent workflow with a real defect, explain why runtime tools miss it, and show how Agentproof catches it statically.

### 5.2 Figures

- Replace Figure 2 with a more complex example (at least 10–15 nodes) where a structural defect is non-obvious.
- Add a figure showing a real defect found in the wild (from the corpus study).
- Add scaling plots from the scalability experiments.

### 5.3 Counterexample Generation

- When a structural check or temporal monitor finds a violation, generate a **witness trace** (a concrete path through the graph that demonstrates the problem).
- This is standard in model checking and dramatically increases practical value.
- Show example counterexamples in the paper.

### 5.4 Abstract and Title

- The abstract is currently adequate but should be tightened after the evaluation is strengthened. Lead with the problem and the key finding ("We find that X% of real-world agent workflows contain structural defects catchable before deployment").
- Consider whether the title "Agentproof" is too tool-branded for a top venue. Some venues prefer descriptive titles.

**Deliverable:** Full paper rewrite with improved figures, motivating example, counterexample traces, and polished prose.

---

## Phase 6 — Supplementary Contributions (Weeks 12–14)

### 6.1 Artifact Packaging

- Package the real-world workflow corpus as a benchmark dataset.
- Provide a stable Python API (`agentproof.verify(graph)` returning structured reports).
- Include CI integration examples (GitHub Actions YAML that runs Agentproof on a workflow definition and fails the build on violations).

### 6.2 User Study (Optional but High Value)

- Recruit 5–10 developers who build agent workflows.
- Give them workflows with known defects. Measure whether Agentproof's output helps them find and fix the defects faster than manual inspection.
- Even a small-scale qualitative study adds significant weight at systems/SE venues.

### 6.3 Appendix

- Full formal definitions and soundness proofs.
- Complete DSL grammar in BNF.
- Full list of structural defects found in the real-world corpus.

---

## Target Venue Strategy

| Venue | Type | Fit | What They Want |
|---|---|---|---|
| USENIX Security | Top security | Good if threat model is strong | Real attacks prevented, formal guarantees |
| IEEE S&P | Top security | Good if formalism is deep | Soundness proofs, adversarial evaluation |
| CCS | Top security | Moderate | Practical impact, real-world deployment |
| ICSE / FSE | Top SE | Strong | Tool evaluation on real codebases, developer study |
| AAAI Workshop (AI Safety) | Workshop | Excellent stepping stone | Novelty of idea, preliminary results OK |
| SaTML | ML safety | Good | Safety guarantees for ML systems |
| AAMAS | Multi-agent | Moderate | Multi-agent coordination focus |

**Recommended path:** Submit the current version (lightly polished) to a **workshop** (AAAI AI Safety, SaTML) for feedback, then target **ICSE or FSE** with the full evaluation, or **USENIX Security** if the threat model and formalism are strong enough.

---

## Summary Checklist

- [ ] Threat model section written
- [ ] Formal graph model with definitions
- [ ] Soundness lemmas and proofs
- [ ] Temporal DSL expanded beyond three patterns
- [ ] Empirical survey of real safety policies mapped to DSL patterns
- [ ] Real-world workflow corpus (15–20 workflows) collected and analyzed
- [ ] Defect study with categorized findings
- [ ] Scalability experiments on synthetic large graphs
- [ ] Comparison table vs. runtime guardrail tools
- [ ] Extractor precision/recall measured
- [ ] Related work expanded to 1.5–2 pages with four subsections
- [ ] Motivating example added to introduction
- [ ] Counterexample/witness trace generation implemented
- [ ] Figures upgraded (complex graph, real defect, scaling plots)
- [ ] README-style language removed, academic tone throughout
- [ ] Abstract revised with key quantitative finding
