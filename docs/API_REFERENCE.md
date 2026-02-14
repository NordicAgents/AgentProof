# API Reference

## Public Interfaces

### `register_tool(definition) -> ToolHandle`
Registers a wrapped tool and metadata.

**Type Definition**
```ts
type ToolDefinition = {
  name: string;
  version: string;
  inputSchema: JsonSchema;
  outputSchema?: JsonSchema;
  permissions: string[];
  costModel: CostModel;
  execute: (input: unknown, ctx: ExecutionContext) => Promise<unknown>;
};
```

### `load_spec(specSource) -> SpecHandle`
Parses and compiles VAC DSL policies.

### `initialize_state(config) -> State`
Creates deterministic initial state.

### `step(state, proposal) -> StepResult`
Performs verification and, when allowed, execution.

**Type Definition**
```ts
type StepResult = {
  decision: "allowed" | "rejected" | "halted";
  output?: unknown;
  newState: State;
  report: VerificationDecisionReport;
};
```

### `generate_report(runArtifacts) -> VerificationReport`
Produces signed/auditable run certificate.

## Notes
- All APIs are pure at the contract boundary except wrapped tool `execute`.
- Deterministic replay requires pinned spec/tool versions and canonical serialization.
