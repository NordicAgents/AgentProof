# Experiment Plan — Compiled Shields for Tool-Using Agents

Drafted 2026-07-11. Target: **ICML 2027** (~late Jan 2027 deadline, ~28 weeks of runway).

## 1. System work (delta from existing codebase)

1. **Shield runtime.** Wrapper at the tool-call boundary: before each tool
   invocation, feed the event (tool name + argument predicates) to the compiled
   DFA (`monitor/ltl.py`); if the transition enters a violating state, block.
   New work is the interception layer:
   - LangGraph tool-node wrapper / middleware (build first — works now)
   - Framework-agnostic MCP proxy (generalize only if weeks 1–6 go smoothly)
2. **Enforcement semantics** (each later an ablation, E4):
   - (a) *block-and-explain* — synthetic tool-error observation naming the
     violated policy; agent re-plans. Likely headline mode (preserves utility).
   - (b) *terminate*
   - (c) *silent-drop*
3. **DSL extension: parameterized propositions.** Current atoms are tool names;
   real policies need argument predicates, e.g.
   `G !(send_email ∧ recipient∉org_domain)`, `G (payment → amount < 500)`.
   Main language work. Replaces paper 1's circular "all 15 policies fit" claim
   with evidence from real attack taxonomies (E5).

## 2. Benchmarks

| Benchmark | Why |
|---|---|
| **AgentDojo** | Standard prompt-injection suite for tool agents; built-in utility + ASR metrics and built-in defenses to compare against |
| **τ-bench** (airline/retail) | Domain policies are natural-language business rules — exactly what the DSL should encode; measures utility under compliance |
| **InjecAgent** | Breadth on indirect injection |
| **AgentHarm** (optional) | Malicious-user (not injected-attacker) threat model; shows generality |

## 3. Baselines

- No defense
- AgentDojo built-in prompt defenses (delimiting/spotlighting, tool filter)
- LLM-judge guardrail screening each tool call (measure cost + stochasticity honestly)
- Llama Guard / NeMo Guardrails where applicable to tool calls

Backbone models: one frontier closed model, Claude, plus open-weights
(Llama/Qwen) so sweeps are cheap and reproducible. Exploration on open weights;
frontier budget reserved for final tables.

## 4. Experiments

- **E1 — Main table.** ASR and benign utility: benchmarks × models × defenses.
  Claim to land: shield drives ASR → ~0 *for policy-covered attacks* with
  utility within a few points of undefended; LLM judge is probabilistic, costs
  tokens, degrades utility.
- **E2 — Utility–security frontier.** Sweep policy strictness permissive →
  paranoid; plot ASR vs. utility. Shield should trace the Pareto frontier;
  judges sit inside it.
- **E3 — Overhead.** Latency and $ per tool call vs. LLM judge; DFA
  product-size and compile-time scaling to hundreds of policies.
  The "provable *and* free" result.
- **E4 — Enforcement-mode ablation.** Block-and-explain vs. terminate vs.
  silent-drop: how often does the agent recover and complete the task?
- **E5 — Coverage study (the honesty experiment).** Attack taxonomy across
  benchmarks → fraction of attack *behaviors* expressible in the DSL, extending
  it where principled. Answers "what about attacks outside the policy?" before
  reviewers ask.
- **E6 — LLM policy synthesis (the ML flavor).** LLM gets tool schemas +
  τ-bench natural-language policy docs → emits DSL policies; validate
  compilability; measure synthesized-shield ASR/utility vs. hand-written.
  Turns "someone must write policies" from weakness into contribution.
- **E7 — Static×runtime synergy (bridge to paper 1).** Graph×DFA product
  proves pre-deployment which policies are unviolable on a workflow (skip
  monitoring) or dead-on-arrival. Reuses `verify/temporal.py` + extractors.
- **E8 — Adaptive attacker (stretch).** Attacker knows the shield and policy;
  can it cause harm within the allowed language? Small red-team study; honest
  residual-risk analysis.

## 5. Theory section

- **Soundness:** shielded execution never emits a policy-violating trace, for
  the enforceable fragment. Anchor in Schneider's security automata + safe-RL
  shielding.
- **Enforceable fragment:** blocking enforces safety but not liveness
  (`F human_review` can't be forced by vetoing — only checked at termination).
  Characterize the seven DSL forms under finite-trace (LTLf) semantics: which
  are shieldable vs. end-of-trace checks. A real result, not decoration.
- **Complexity:** O(1) per event post-compilation; DFA size bounds in policy size.

## 6. Timeline (28 weeks from 2026-07-11)

| Weeks | Dates (approx) | Work |
|---|---|---|
| 1–3 | Jul 13 – Aug 2 | Shield runtime + AgentDojo integration; pilot on one model |
| 4–6 | Aug 3 – Aug 23 | Parameterized-proposition DSL; τ-bench encoding; baselines wired |
| 7–10 | Aug 24 – Sep 20 | Main sweep E1–E3 |
| 11–14 | Sep 21 – Oct 18 | E4–E6; draft theory section; **workshop submission window** |
| 15–19 | Oct 19 – Nov 22 | E7, E8, ablations; full draft |
| 20–24 | Nov 23 – Dec 27 | Red-team own claims; polish; internal review |
| 25–28 | Dec 28 – Jan 24 | Buffer (something in weeks 1–10 will slip) |

## 7. Risks

- **"Runtime verification is old."** Novelty = no-manual-modeling enforcement
  for LLM agents + measured utility–security frontier + enforceable-fragment
  result for finite agent traces + policy synthesis. State in intro before a
  reviewer states it as weakness #1.
- **Coverage gap eats the headline.** If E5 shows only ~40% of attack behaviors
  expressible, reframe as "provable floor + judge for the remainder" and add a
  shield+judge stacked-defense experiment.
- **API cost of sweeps.** Open-weights for exploration; frontier models only
  for final tables.

## 8. Early decisions

- **Interception point:** framework wrapper first; MCP proxy only if on
  schedule (decide end of week 6).
- **Verify current-cycle deadlines** (ICML 2027, NeurIPS 2026 workshops) —
  dates above follow historical patterns and need confirmation.
