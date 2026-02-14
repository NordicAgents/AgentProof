# Integration: LangGraph

## Adapter Architecture
Use a VAC adapter node as the only side-effect execution node in the graph:
- Planner nodes emit proposed actions.
- Adapter node calls `step()`.
- Downstream nodes consume verified outputs only.

## Required Hooks
- Pre-execution interception hook for all tool intents.
- State serialization hook for checkpoint/replay.
- Error propagation hook for rejection and halt events.

## Tool Interception Rules
- Disable direct tool executors in graph runtime.
- Route all tool calls through VAC wrapper registry.
- Preserve LangGraph run IDs in action metadata.

## Example Workflow
1. Planner node proposes `SendEmail` action.
2. VAC adapter validates and verifies.
3. If allowed, wrapper executes email tool.
4. Adapter returns result + new state snapshot to graph.
