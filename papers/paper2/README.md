# Paper 2 — Compiled Shields for Tool-Using Agents

**Working thesis.** Declarative temporal safety policies, compiled once into DFA
shields that intercept an agent's tool calls, give *deterministic, provable*
enforcement at microsecond overhead — matching or beating LLM-judge guardrails
on attack prevention while losing almost no benign task utility.

**Target venue:** ICML 2027 (deadline ~late January 2027).
**Early-signal option:** NeurIPS 2026 safety/agents workshop (~October 2026) with E1–E3 only.

**Relationship to paper 1** (`papers/paper1/`, Agentproof static verification,
ICLR 2027 / FSE track): paper 1's mining study showed real topology-defect base
rates are ~0% and static extraction fidelity is the bottleneck. Paper 2 moves the
DFA machinery to where the real risk lives — runtime behavior — and reuses:

- `src/agentproof/monitor/ltl.py` — LTL DSL → DFA compilation, runtime monitor
- `src/agentproof/verify/temporal.py` — graph×DFA product (used in E7 static×runtime synergy)
- `src/agentproof/graph/extract/_*.py` — framework extractors (shield interception points)

**Threat model.** Prompt-injected or misaligned tool-using agent; policies are
trusted, authored (or LLM-synthesized then human-approved) by the deployer.
Shield sits at the tool-call boundary and can veto/rewrite calls.

**Contributions targeted:**
1. No-manual-modeling policy enforcement for LLM agents (framework wrapper + MCP proxy).
2. Measured utility–security frontier: deterministic shield vs. probabilistic guardrails.
3. Theory: enforceable fragment of the DSL under finite-trace (LTLf) semantics;
   soundness of shielded execution; O(1) per-event complexity.
4. LLM policy synthesis from natural-language rules (τ-bench domain docs) with
   compile-time validation.

See [EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md) for the full plan, timeline, and risks.
