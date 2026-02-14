# Verification Report Format

## Certificate Schema (JSON)
```json
{
  "report_version": "1.0",
  "run_id": "string",
  "spec_hash": "sha256",
  "engine_version": "string",
  "decision_summary": {"allowed": 0, "rejected": 0, "halted": 0},
  "assumptions": ["..."],
  "bounds": {"bmc_k": 0, "timeouts_ms": 0},
  "artifacts": {
    "trace_hash": "sha256",
    "state_hash_final": "sha256",
    "counterexamples": []
  },
  "reproducibility": {
    "deterministic_replay_passed": true,
    "tool_versions": {}
  }
}
```

## Required Fields
- Report/spec/engine version identifiers.
- Assumptions and verification bounds.
- Trace and final state hashes.
- Replay reproducibility status.

## Hashing & Versioning
- SHA-256 over canonical JSON artifacts.
- Include schema version and migration notes for compatibility.

## Reproducibility Requirements
- Must provide enough metadata to replay decisions deterministically.
- Any missing tool/version pin invalidates strong reproducibility claim.
