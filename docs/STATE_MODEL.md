# State Model

## Explicit State Structure
```text
State {
  version: string
  run_id: string
  memory: Map<String, Value>
  budgets: {max_calls, used_calls, max_cost, used_cost, max_retries, used_retries}
  permissions: Set<String>
  trace: List<TraceEvent>
  monitor_state: Map<RuleId, AutomatonState>
  status: ready | completed | halted
}
```

## Memory Layout
- Namespaced key-value tree (`session.*`, `user.*`, `workflow.*`).
- Values restricted to deterministic serializable primitives/objects.

## Budget Counters
- Calls: count of successful wrapper invocations.
- Cost: accumulated normalized cost units.
- Retries: per-action or global retry budget.

## Permissions
- Capability tokens (e.g., `email.send`, `payments.transfer`).
- Static baseline + dynamic grants/revocations recorded in trace.

## Trace Representation
Each event includes:
- `step_index`
- `proposal_hash`
- `decision`
- `violations[]`
- `tool_call` (if allowed)
- `state_hash_before`, `state_hash_after`

## Serialization Format
- Canonical JSON (sorted keys, UTF-8, no insignificant whitespace).
- Stable hashing over canonical bytes.

## Deterministic Replay Design
- Replay uses recorded proposals and stubbed tool outputs.
- Transition and monitor state recomputed from genesis state.
- Final hash and report hash must match original run.
