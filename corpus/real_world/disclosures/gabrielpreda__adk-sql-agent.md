# The "security router" can't actually stop unsafe requests (`sql_agent/agent.py`)

Hi, and thanks for sharing adk-sql-agent — the security-first framing is a nice
idea.

I'm writing as part of an academic study of agent-workflow verification, in which
we review publicly available agent code for control-flow and safety patterns. I
believe the security gate in the SQL pipeline doesn't take effect the way the code
intends, so unsafe requests can proceed to SQL generation/execution.

## What I looked at

`sql_agent/agent.py`, pinned at commit
`ef9206ea3d5c4a89b956481043a1508ff433a0fc`:

https://github.com/gabrielpreda/adk-sql-agent/blob/ef9206ea3d5c4a89b956481043a1508ff433a0fc/sql_agent/agent.py

## What I found

`security_router_agent` is named and instructed as a gate that "exits on not
secure," but it has no mechanism to actually terminate the pipeline:

- `security_router_agent` (lines **95–101**) is a plain `LlmAgent` — no tools, no
  callbacks, no escalation. Its description (line 98) says "exits on not secure,
  continues on secure" and its instruction (lines 73–87) says "NOT SECURE → ...
  system exits," but those are just words the model emits.
- It sits inside the root `SequentialAgent` (lines **134–142**), which runs **all**
  of its sub-agents in order unconditionally. There is no branch that a rejection
  message can trigger.
- As a result, a request the safety agent flags NOT SECURE (e.g. a `DROP TABLE` /
  `DELETE FROM` / `TRUNCATE` request) is not stopped: control falls through to the
  refinement loop (lines **107–117**) that rewrites, generates, and runs SQL.

The code comment at lines **130–132** actually acknowledges this — it notes that
"all agents execute in sequence" and hopes the refinement loop "will handle it
gracefully." I'd gently suggest that relying on a downstream LLM to notice a
rejection message isn't a dependable control.

One more supporting detail: the sibling file `sql_agent/agent_v2.py` (same commit)
defines a `loop_termination_callback` (lines 16–19) that only logs and is never
wired to `end_invocation`/`escalate` — which reads to me like a termination
mechanism that was started but not finished.

## Why it matters

The repo advertises a security layer, but as wired it's a no-op: an unsafe query
reaches generation/execution anyway. Anyone using this as a template inherits a
safety control that doesn't fire.

## A possible minimal fix

Give the security step real terminating power instead of relying on prompt text:

- Implement it with a callback that calls `tool_context.actions.escalate` (or
  `end_invocation`) on a NOT-SECURE result, so the pipeline actually stops; **or**
- Restructure so the security decision conditionally gates entry to the refinement
  loop (e.g. the router routes to the loop only on SECURE), rather than sitting as
  one more unconditional step in a `SequentialAgent`.

A `SequentialAgent` won't stop just because a sub-agent's text says "this is the
END," so the exit has to be expressed in control flow.

## Offer

Glad to help wire up an escalate-based gate as a small PR if that's welcome, or to
stand corrected if there's a termination path I missed.

Thanks for the project.

— [SENDER]
(part of an academic study of agent-workflow verification)
</content>
