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

**Type Definition (contract-aligned)**
```ts
type VerificationReport = {
  report_version: string;
  contract_family: "vac.verification_report";
  contract_revision: number;
  run_id: string;
  spec_hash: string;
  engine_version: string;
  decision_summary: { allowed: number; rejected: number; halted: number };
  assumptions: string[];
  bounds: { bmc_k: number; timeouts_ms: number };
  solver_queries: SolverQueryMetadata[];
  temporal_monitor: TemporalMonitorTransitions;
  bmc: BmcOutcomes;
  artifacts: {
    trace_hash: string;
    state_hash_final: string;
    counterexamples: NormalizedCounterexample[];
  };
  hashes: {
    decision_hash: string;
    state_hash: string;
    report_hash: string;
  };
  reproducibility: {
    deterministic_replay_passed: boolean;
    canonical_serialization: "JCS-RFC8785";
    tool_versions: Record<string, string>;
    nondeterminism_controls: string[];
  };
  signatures: {
    signature_scheme: string;
    key_id: string;
    report_signature: string;
  };
};
```

## Notes
- All APIs are pure at the contract boundary except wrapped tool `execute`.
- Deterministic replay requires pinned spec/tool versions and canonical serialization.
- Report contract details and examples are defined in `docs/VERIFICATION_REPORT_FORMAT.md` and `docs/VERIFICATION_REPORT_EXAMPLES.md`.
