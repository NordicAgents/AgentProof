# Verification Report Format

This document defines the canonical report contract emitted by the Phase 2 verification pipeline and consumed by Phase 3 certificate/replay/forensic tooling.

## Contract Versioning
- `report_version`: semantic version for this report schema.
- `contract_family`: fixed string `vac.verification_report`.
- `contract_revision`: monotonic integer incremented on additive/compatible changes.
- Backward-incompatible changes must increment major `report_version` and document migration notes.

## Canonical Report Schema (JSON)
```json
{
  "report_version": "2.0.0",
  "contract_family": "vac.verification_report",
  "contract_revision": 2,
  "run_id": "string",
  "spec_hash": "sha256",
  "engine_version": "string",
  "decision_summary": {
    "allowed": 0,
    "rejected": 0,
    "halted": 0
  },
  "assumptions": ["..."],
  "bounds": {
    "bmc_k": 0,
    "timeouts_ms": 0
  },
  "solver_queries": [
    {
      "query_id": "string",
      "step_index": 0,
      "property_id": "string",
      "kind": "safety|liveness|permission|budget|custom",
      "backend": "z3|cvc5|other",
      "result": "sat|unsat|unknown|timeout|error",
      "elapsed_ms": 0,
      "model_hash": "sha256",
      "assumption_hash": "sha256",
      "query_hash": "sha256"
    }
  ],
  "temporal_monitor": {
    "initial_state": {
      "rule-1": "S0"
    },
    "transitions": [
      {
        "step_index": 0,
        "rule_id": "rule-1",
        "from": "S0",
        "event": "ApprovePayment",
        "to": "S1",
        "status": "ok|violated|satisfied|pending"
      }
    ],
    "final_state": {
      "rule-1": "S1"
    }
  },
  "bmc": {
    "status": "proved|counterexample|inconclusive|not_run",
    "max_bound": 0,
    "checked_bounds": [0, 1, 2],
    "outcomes": [
      {
        "property_id": "string",
        "bound": 2,
        "result": "proved|counterexample|inconclusive",
        "solver_query_ids": ["q-1", "q-2"]
      }
    ]
  },
  "artifacts": {
    "trace_hash": "sha256",
    "state_hash_final": "sha256",
    "counterexamples": [
      {
        "counterexample_id": "string",
        "property": {
          "property_id": "string",
          "property_kind": "invariant|temporal|safety|liveness|custom",
          "description": "string"
        },
        "bound": 2,
        "witness_trace": [
          {
            "step_index": 0,
            "proposal_hash": "sha256",
            "state_hash_before": "sha256",
            "state_hash_after": "sha256",
            "action_type": "string",
            "decision": "allowed|rejected|halted"
          }
        ],
        "violated_constraints": [
          {
            "constraint_id": "string",
            "constraint_type": "invariant|temporal|budget|permission|custom",
            "message": "string"
          }
        ]
      }
    ]
  },
  "hashes": {
    "decision_hash": "sha256",
    "state_hash": "sha256",
    "report_hash": "sha256"
  },
  "reproducibility": {
    "deterministic_replay_passed": true,
    "canonical_serialization": "JCS-RFC8785",
    "tool_versions": {
      "tool.name": "1.2.3"
    },
    "nondeterminism_controls": [
      "stubbed_tool_outputs",
      "fixed_random_seed"
    ]
  },
  "signatures": {
    "signature_scheme": "ed25519",
    "key_id": "string",
    "report_signature": "base64"
  }
}
```

## Required Fields
- Report contract/version identifiers: `report_version`, `contract_family`, `contract_revision`.
- Identity and provenance: `run_id`, `spec_hash`, `engine_version`.
- Decision rollup and policy context: `decision_summary`, `assumptions`, `bounds`.
- Phase 2 formal evidence: `solver_queries`, `temporal_monitor.transitions`, and `bmc.outcomes`.
- Replay parity hashes: `hashes.decision_hash`, `hashes.state_hash`, `hashes.report_hash`.
- Normalized counterexample payloads under `artifacts.counterexamples`.
- Reproducibility block including deterministic serialization declaration.

## Deterministic Serialization Rules
All hash/signature inputs MUST be produced from canonical bytes:
1. Serialize JSON using RFC 8785 (JCS): UTF-8, lexicographic key ordering, deterministic numeric representation, no insignificant whitespace.
2. Arrays MUST preserve logical order:
   - `solver_queries`: ascending `step_index`, then `query_id`.
   - `temporal_monitor.transitions`: ascending `step_index`, then `rule_id`.
   - `bmc.outcomes`: ascending `property_id`, then `bound`.
   - `counterexamples`: ascending `counterexample_id`.
3. Objects in `counterexamples` MUST use stable field ordering exactly as documented: `property`, `bound`, `witness_trace`, `violated_constraints`.
4. `report_hash` is SHA-256 of the full canonical report JSON with `signatures.report_signature` set to empty string during pre-sign hashing.
5. `decision_hash` is SHA-256 of canonical JSON containing decision events only (`step_index`, `decision`, `violations`, `proposal_hash`).
6. `state_hash` is SHA-256 of canonical JSON of the final normalized state snapshot.

## Counterexample Normalization
Each counterexample payload is contractually normalized for replay/certification parity:
- `property`: stable property descriptor (`property_id`, `property_kind`, `description`).
- `bound`: integral bound at which violation is witnessed.
- `witness_trace`: deterministic step sequence with state/proposal hashes.
- `violated_constraints`: deterministic list of violated constraints and messages.

Producers MUST NOT emit implementation-specific field names or unstable ordering in these sections.

## Phase 2 -> Phase 3 Consumption Requirements
Phase 3 certificate and forensic tools can assume:
- Every solver/BMC result is traceable via `solver_query_ids` and `solver_queries.query_id`.
- Temporal obligations are replayable from `temporal_monitor.initial_state`, `transitions`, and `final_state`.
- Counterexample witness traces are self-contained and hash-stable.
- Certificate verification can recompute `decision_hash`, `state_hash`, and `report_hash` byte-for-byte.

If any required field is absent, tooling must degrade to `inconclusive` rather than asserting parity.

## Examples
Concrete examples are provided in `docs/VERIFICATION_REPORT_EXAMPLES.md`.
