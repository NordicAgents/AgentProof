# Integration: OpenAI

## Tool Call Interception
- Treat model tool calls as untrusted proposals.
- Convert each tool call into VAC action schema.
- Execute only through `step()` decision path.

## Proposal Formatting
- Map tool name -> `tool_name`.
- Map arguments -> `input`.
- Attach model/run metadata (`response_id`, `turn_id`, `correlation_id`).
- Record raw proposal digest for audit.

## Streaming Considerations
- Buffer partial tool-call arguments until JSON is complete.
- Validate only finalized proposal payload.
- Emit interim UX events without side effects.

## Model Configuration Guidance
- Prefer deterministic settings when testing/replay (`temperature=0`).
- Use explicit tool schemas and strict mode where available.
- Keep system prompts aligned with registered policy names to reduce futile proposals.
