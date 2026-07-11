export const meta = {
  name: 'realworld-validate-triage',
  description: 'Ground-truth validation of AST extraction + adversarial defect triage on mined GitHub workflows',
  phases: [
    { title: 'GroundTruth', detail: 'independent reference graph per sampled source file' },
    { title: 'Triage', detail: 'label each flagged defect: real / artifact / intentional' },
    { title: 'Verify', detail: 'adversarial re-check of triage labels' },
  ],
}

// args = {
//   groundTruth: [{slug, framework, source_path, graph_path}],
//   triage:      [{slug, framework, source_path, graph_path, defects:[{check_id, detail, witness}]}],
// }
const GT = (args && args.groundTruth) || []
const TR = (args && args.triage) || []

const ID_CONVENTIONS = `
NODE-ID CONVENTIONS (must match these so the reference aligns with the automatic extractor):
- LangGraph: the node id is EXACTLY the first string argument to add_node("...").
  Entry sentinel id = "__start__", exit sentinel id = "__end__". END -> "__end__", START -> "__start__".
- CrewAI: one node per Task(...). id = the task's description string, first 50 chars, lowercased,
  spaces replaced with underscores. Tasks run sequentially in Crew(tasks=[...]) order unless process= says otherwise.
- AutoGen: one node per participant/agent. id = the agent's Python variable name as passed to the group chat.
  RoundRobin adds a loop edge from the last agent back to the first.
- ADK: one node per sub_agent. id = the sub_agent's name string (or variable). SequentialAgent chains them;
  ParallelAgent fans __start__ out to each and each back to __end__.
Always include the "__start__" (kind entry) and "__end__" (kind exit) sentinels.`

const KIND_RULES = `
NODE KINDS (pick exactly one per node): entry, exit, tool, llm, router, human, subgraph, passthrough.
- tool: the node's job is to call an external tool / API / function (or the framework binds tools to it).
- llm: an inference / agent-reasoning / generation step with no external side-effecting tool.
- router: a node whose outgoing edges are conditional branches (dispatch/classify-and-route).
- human: a human-in-the-loop step: approval gate, manual review, input()/interrupt, "ask the user".
- subgraph: a node that embeds a nested workflow graph.
EDGE KINDS: direct, conditional (from routers / add_conditional_edges), parallel, loop (cycles/round-robin).`

const GT_SCHEMA = {
  type: 'object',
  required: ['slug', 'nodes', 'edges', 'entry_id', 'exit_ids', 'notes'],
  properties: {
    slug: { type: 'string' },
    framework: { type: 'string' },
    entry_id: { type: 'string' },
    exit_ids: { type: 'array', items: { type: 'string' } },
    nodes: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', 'kind'],
        properties: {
          id: { type: 'string' },
          kind: { enum: ['entry', 'exit', 'tool', 'llm', 'router', 'human', 'subgraph', 'passthrough'] },
          label: { type: 'string' },
          tools: { type: 'array', items: { type: 'string' } },
        },
      },
    },
    edges: {
      type: 'array',
      items: {
        type: 'object',
        required: ['source', 'target'],
        properties: {
          source: { type: 'string' },
          target: { type: 'string' },
          kind: { enum: ['direct', 'conditional', 'parallel', 'loop'] },
        },
      },
    },
    confidence: { enum: ['high', 'medium', 'low'] },
    notes: { type: 'string' },
  },
}

const TRIAGE_SCHEMA = {
  type: 'object',
  required: ['slug', 'labels'],
  properties: {
    slug: { type: 'string' },
    labels: {
      type: 'array',
      items: {
        type: 'object',
        required: ['check_id', 'label', 'justification'],
        properties: {
          check_id: { type: 'string' },
          detail: { type: 'string' },
          label: { enum: ['real_defect', 'extraction_artifact', 'intentional', 'arguable'] },
          confidence: { enum: ['high', 'medium', 'low'] },
          justification: { type: 'string' },
        },
      },
    },
  },
}

const VERIFY_SCHEMA = {
  type: 'object',
  required: ['slug', 'reviews'],
  properties: {
    slug: { type: 'string' },
    reviews: {
      type: 'array',
      items: {
        type: 'object',
        required: ['check_id', 'agree', 'final_label'],
        properties: {
          check_id: { type: 'string' },
          agree: { type: 'boolean' },
          final_label: { enum: ['real_defect', 'extraction_artifact', 'intentional', 'arguable'] },
          reason: { type: 'string' },
        },
      },
    },
  },
}

function gtPrompt(item) {
  return `You are validating an automatic workflow-graph extractor by building an INDEPENDENT ground-truth graph.

Read the real ${item.framework} source file at:
  ${item.source_path}

Reconstruct the TRUE agent workflow graph purely from the source (do NOT look at the extractor output).
${ID_CONVENTIONS}
${KIND_RULES}

Rules:
- Only include nodes/edges that genuinely exist in the source. If the workflow is built dynamically
  (nodes added in loops/comprehensions, edges from variables), infer the concrete graph if determinable;
  if a portion is genuinely undeterminable from static source, omit it and say so in notes.
- Use kind "tool" only when the node actually invokes an external tool/API/function or has tools bound.
- Set confidence low if the file is a partial snippet, a library wrapper, or not really a workflow definition.
- Return slug="${item.slug}", framework="${item.framework}", and put any caveats in notes.`
}

function triagePrompt(item) {
  const defectList = item.defects
    .map((d, i) => `  ${i + 1}. check_id=${d.check_id} :: ${d.detail}${d.witness ? ` :: witness=${d.witness}` : ''}`)
    .join('\n')
  return `A static verifier flagged defects in a workflow graph AUTOMATICALLY EXTRACTED from real GitHub source.
Your job: for EACH flagged defect decide whether it is a genuine problem in the real workflow, or merely an
artifact of imperfect extraction, or an intentional design choice.

Real ${item.framework} source file:  ${item.source_path}
Extracted graph JSON:                ${item.graph_path}

Flagged defects:
${defectList}

Read BOTH files. For each defect assign one label:
- real_defect: the actual source workflow really has this problem (e.g., a node truly has no outgoing
  transition, an exit is truly unreachable, a router truly uses non-conditional edges, a sensitive path
  truly bypasses human review). A developer would want to fix it.
- extraction_artifact: the defect exists ONLY because the AST extractor missed edges/nodes or misclassified
  a node. The real workflow is fine. (This is common when edges are built from variables, loops, END
  sentinels, or conditional maps the static extractor cannot resolve.)
- intentional: the pattern is a deliberate design choice (e.g., a terminal node that intentionally halts,
  or a genuinely low-risk workflow that legitimately needs no human gate).
- arguable: genuinely unclear from the source.

Ground every label in specific evidence from the source (quote the relevant lines). Return slug="${item.slug}".`
}

function verifyPrompt(item, primary) {
  return `Adversarially re-check another reviewer's triage of extraction-flagged defects. Try to OVERTURN each
label; only agree if the evidence in the source truly supports it.

Real ${item.framework} source:  ${item.source_path}
Extracted graph JSON:           ${item.graph_path}

Primary reviewer's labels:
${primary.labels.map((l) => `  - ${l.check_id}: ${l.label} (${l.confidence || 'n/a'}) -- ${l.justification}`).join('\n')}

Read the source yourself. For each check_id, state whether you agree; if not, give the correct final_label
and why. If primary and your view disagree and neither is clearly right, final_label = "arguable".
Return slug="${item.slug}".`
}

// ---- Phase 1: ground-truth reference graphs (independent, single careful agent each) ----
phase('GroundTruth')
log(`Building ${GT.length} ground-truth reference graphs`)
const groundTruth = await parallel(
  GT.map((item) => () =>
    agent(gtPrompt(item), {
      label: `gt:${item.slug}`,
      phase: 'GroundTruth',
      agentType: 'general-purpose',
      schema: GT_SCHEMA,
    }).then((g) => (g ? { ...g, framework: g.framework || item.framework } : null))
  )
)

// ---- Phase 2+3: triage each defective workflow, then adversarially verify ----
phase('Triage')
log(`Triaging ${TR.length} defective workflows (primary label -> adversarial verify)`)
const triaged = await pipeline(
  TR,
  (item) =>
    agent(triagePrompt(item), {
      label: `triage:${item.slug}`,
      phase: 'Triage',
      agentType: 'general-purpose',
      schema: TRIAGE_SCHEMA,
    }).then((primary) => ({ item, primary })),
  ({ item, primary }) => {
    if (!primary) return null
    return agent(verifyPrompt(item, primary), {
      label: `verify:${item.slug}`,
      phase: 'Verify',
      agentType: 'general-purpose',
      schema: VERIFY_SCHEMA,
    }).then((verdict) => {
      // reconcile: keep primary label when verifier agrees; else use verifier final_label
      const vmap = {}
      for (const r of (verdict && verdict.reviews) || []) vmap[r.check_id] = r
      const reconciled = primary.labels.map((l) => {
        const v = vmap[l.check_id]
        if (!v) return { ...l, final_label: l.label, verified: false }
        return {
          ...l,
          final_label: v.agree ? l.label : v.final_label,
          verified: true,
          agreed: !!v.agree,
          verifier_reason: v.reason || '',
        }
      })
      return { slug: item.slug, framework: item.framework, labels: reconciled }
    })
  }
)

return {
  groundTruth: groundTruth.filter(Boolean),
  triage: triaged.filter(Boolean),
  counts: { gt: GT.length, triage: TR.length },
}
