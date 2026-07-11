export const meta = {
  name: 'reframe-paper1-spine',
  description: 'Reframe Agentproof abstract/contributions/conclusion to the honest three-legged story',
  phases: [
    { title: 'Draft', detail: '3 independent reframes, each leading a different leg' },
    { title: 'Synthesize', detail: 'judge + graft best into final spine for AAAI' },
  ],
}

const FACTS = `
PAPER: "Agentproof: Static Verification of Agent Workflow Graphs". Target venue AAAI-27
(broad AI venue, ~7 content pages, tough reviewing), fallback ICLR-27.

THE SYSTEM (unchanged, real):
- Automatically extracts a UNIFIED abstract graph model from four agent frameworks
  (LangGraph, CrewAI, AutoGen, Google ADK) directly from framework APIs -- no manual modeling
  (unlike SPIN/NuSMV which need hand-written Promela/SMV).
- Six structural checks (exit reachability, reverse-reachability/livelock, dead ends, router
  shape, human-gate presence/coverage, tool declarations) with witness-trace generation.
- A temporal policy DSL (safety fragment of LTL, seven forms) compiled to DFAs, evaluated both
  STATICALLY via a graph x DFA product construction and at runtime over event traces.

THE NEW REAL-WORLD STUDY (this is the pivot -- results are honest and must be stated plainly):
- Mined 277 real workflows from 149 public GitHub repos (LangGraph+CrewAI; AutoGen+ADK being added).
- Validated a 60-workflow sample with independent LLM-agent ground-truth graphs + adversarial triage.
- Real workflows are tiny: median 2 non-sentinel nodes, mostly static linear pipelines.
- The static AST-fallback extractor achieves node P/R ~0.93/0.90 but EDGE-RECALL only 0.68 and
  node-kind accuracy 0.74 on real code (vs perfect on stubs). Dominant error: tool->llm (nodes that
  call tools in their body without declared bindings).
- Of 131 flagged defects, only 1 (0.8%) is a genuine bug: 56% are EXTRACTION ARTIFACTS, 38% are
  INTENTIONAL design choices. Validated real structural-defect rate ~= 0%.
- The human-gate policy fires on 98% of workflows but 91% of those firings are intentional
  (legitimately low-risk tasks) -> the check needs risk-awareness to be useful.
- Cross-check confirms mechanism: mean edge-recall 0.51 for artifact-labeled workflows vs 1.0 for
  the one real defect. Static checks are only as sound as the recovered topology.

THE THREE-LEGGED VALUE STORY (the reframe -- the paper's contribution must survive "defects are rare"):
1. A MEASUREMENT INSTRUMENT + the first real-world base-rate study of agent-workflow topology defects.
   The finding that defects are rare is itself a contribution (nobody had measured it).
2. A DIAGNOSIS the field can act on: extraction FIDELITY (not the check algorithms) is the binding
   constraint, quantified, with a failure-mode taxonomy.
3. A concrete JOB for the static machinery that does NOT depend on defects existing: the graph x DFA
   product proves which temporal policies can NEVER reach a violation on a given workflow, so those
   runtime monitors can be provably SKIPPED (pruned) at enforcement time. This bridges to follow-up
   work on runtime shields.

HARD RULES:
- Be honest. Do NOT claim defects are common. Do NOT overclaim. The old abstract's "27%/55% defects"
  framing is RETIRED (those were rates on an author-built benchmark, now known not to generalize).
- The curated 18-workflow benchmark still exists but is now positioned as a controlled detection test,
  not evidence of prevalence.
- Abstract must be self-consistent with the contributions and conclusion.
- AAAI audience: crisp, technical, no marketing. ~150-200 word abstract.`

const CURRENT_ABSTRACT = `Agent frameworks increasingly encode tool-using behavior as explicit workflow graphs, yet safety enforcement remains a runtime concern. These frameworks expose analyzable graph structure through their APIs, enabling pre-deployment static verification. This paper presents Agentproof, a system that automatically extracts a unified abstract graph model from four major agent frameworks (LangGraph, CrewAI, AutoGen, Google ADK), applies six structural checks with witness trace generation, and evaluates temporal safety policies via a DSL compiled to DFAs -- both statically through a graph x DFA product construction and at runtime. In a curated benchmark of 18 author-constructed workflows, 27% contain structural defects and 55% violate a human-gate policy when enforced. All 15 temporal policies fit within the seven-form DSL fragment, and verification completes in sub-second time for graphs up to 5,000 nodes.`

const CURRENT_CONTRIBUTIONS = `1) A cross-framework extraction pipeline: extractors for four major agent frameworks that bridge heterogeneous representations into a unified abstract workflow model, eliminating the manual modeling of general-purpose model checkers.
2) A pre-deployment verification pipeline: six structural checks with witness-trace generation plus a temporal policy DSL covering the safety fragment of LTL, compiled to DFAs.
3) An empirical evaluation on 18 curated workflows demonstrating that structural defects and policy violations are common, with sub-second verification up to 5,000 nodes.`

const CURRENT_CONCLUSION = `Agent frameworks already encode behavior as explicit workflow graphs; Agentproof leverages this for pre-deployment verification without runtime overhead. It provides a unified graph model with six structural checks and witness traces, a temporal DSL over the safety fragment of LTL with static and runtime modes, and extractors for four frameworks. In the 18-workflow curated benchmark, 5 contain structural defects and 10 lack a human gate. The primary contribution is not the (standard) graph algorithms but the new domain, the extractor engineering, and the empirical finding that real workflows contain detectable defects. Static verification complements runtime guardrails.`

const OUT_SCHEMA = {
  type: 'object',
  required: ['abstract', 'contributions', 'conclusion'],
  properties: {
    abstract: { type: 'string', description: 'One paragraph, ~150-200 words, AAAI-style.' },
    contributions: {
      type: 'array', minItems: 3, maxItems: 5,
      items: { type: 'string', description: 'One contribution, self-contained sentence(s).' },
    },
    conclusion: { type: 'string', description: 'One-to-two paragraph conclusion, honest framing.' },
    emphasis: { type: 'string' },
    notes: { type: 'string' },
  },
}

const EMPHASES = [
  { key: 'study-first', lead: 'Lead with leg 1: this is the FIRST honest real-world base-rate study; the system is the instrument that made it possible. Frame the negative prevalence result as the headline empirical contribution.' },
  { key: 'diagnosis-first', lead: 'Lead with leg 2: the central finding is that extraction FIDELITY, not the checks, is the binding constraint for static verification of agent workflows; quantify it and give the failure-mode taxonomy as the spine.' },
  { key: 'utility-first', lead: 'Lead with leg 3: reframe the static graph x DFA machinery around a job that survives rare defects -- provably pruning runtime monitors (which policies can never fire) -- positioning the system within a static+runtime safety stack.' },
]

phase('Draft')
log('Drafting 3 independent reframes (study-first / diagnosis-first / utility-first)')
const drafts = await parallel(
  EMPHASES.map((e) => () =>
    agent(
      `You are rewriting the ABSTRACT, CONTRIBUTIONS, and CONCLUSION of an AI systems paper to an honest new framing.\n\n${FACTS}\n\nYOUR ASSIGNED EMPHASIS: ${e.lead}\nAll three legs must still appear, but lead with your assigned one.\n\nCURRENT ABSTRACT (to replace):\n${CURRENT_ABSTRACT}\n\nCURRENT CONTRIBUTIONS (to replace):\n${CURRENT_CONTRIBUTIONS}\n\nCURRENT CONCLUSION (to replace):\n${CURRENT_CONCLUSION}\n\nWrite plain prose (no LaTeX commands). Return abstract, contributions (3-5 items), conclusion, and set emphasis="${e.key}".`,
      { label: `draft:${e.key}`, phase: 'Draft', agentType: 'general-purpose', schema: OUT_SCHEMA }
    )
  )
)

phase('Synthesize')
log('Synthesizing final spine from the 3 drafts')
const valid = drafts.filter(Boolean)
const synthesis = await agent(
  `You are the senior author finalizing the ABSTRACT, CONTRIBUTIONS, and CONCLUSION for an AAAI submission.\n\n${FACTS}\n\nThree co-authors each drafted a version leading with a different leg. Choose the strongest framing and GRAFT the best sentences from each into one coherent, honest, self-consistent spine. The abstract must lead cleanly, state the negative base-rate finding without spin, and make clear why the work matters anyway (measurement + diagnosis + monitor-pruning). Contributions must match the abstract. Conclusion must not reintroduce "defects are common".\n\nDRAFTS:\n${valid.map((d, i) => `--- DRAFT ${i + 1} (${d.emphasis}) ---\nABSTRACT: ${d.abstract}\nCONTRIBUTIONS:\n${(d.contributions || []).map((c) => '  - ' + c).join('\n')}\nCONCLUSION: ${d.conclusion}`).join('\n\n')}\n\nReturn the FINAL abstract (~150-200 words), contributions (3-5 items), and conclusion. In notes, name which draft you led with and the single biggest risk in this framing.`,
  { label: 'synthesize:final', phase: 'Synthesize', agentType: 'general-purpose', schema: OUT_SCHEMA }
)

return { final: synthesis, drafts: valid }
