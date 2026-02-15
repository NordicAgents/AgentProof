# Verification Report Examples

These examples follow `docs/VERIFICATION_REPORT_FORMAT.md` and are intentionally compact while preserving canonical field ordering.

## Example A: No Counterexample (BMC Proved)
```json
{
  "report_version": "2.0.0",
  "contract_family": "vac.verification_report",
  "contract_revision": 2,
  "run_id": "run-2026-0001",
  "spec_hash": "6f8b8f89b2f18c6ef8fd5c6839f3e6af20e9c3cd496f4d1d71f5f3ca347d29ff",
  "engine_version": "vac-engine/2.0.0",
  "decision_summary": {
    "allowed": 4,
    "rejected": 1,
    "halted": 0
  },
  "assumptions": [
    "tool outputs stubbed",
    "clock excluded from transition logic"
  ],
  "bounds": {
    "bmc_k": 5,
    "timeouts_ms": 2000
  },
  "solver_queries": [
    {
      "query_id": "q-0001",
      "step_index": 1,
      "property_id": "inv.no_delete",
      "kind": "safety",
      "backend": "z3",
      "result": "unsat",
      "elapsed_ms": 14,
      "model_hash": "e3b0c44298fc1c149afbf4c8996fb924...",
      "assumption_hash": "5707a5213e7f8f3981a2dd9480f1e970...",
      "query_hash": "1342f8f0c2b63b2ce03db0f676b17779..."
    }
  ],
  "temporal_monitor": {
    "initial_state": {
      "rule.payments.must_ledger_write": "S0"
    },
    "transitions": [
      {
        "step_index": 2,
        "rule_id": "rule.payments.must_ledger_write",
        "from": "S0",
        "event": "ApprovePayment",
        "to": "S1",
        "status": "pending"
      },
      {
        "step_index": 3,
        "rule_id": "rule.payments.must_ledger_write",
        "from": "S1",
        "event": "LedgerWrite",
        "to": "S2",
        "status": "satisfied"
      }
    ],
    "final_state": {
      "rule.payments.must_ledger_write": "S2"
    }
  },
  "bmc": {
    "status": "proved",
    "max_bound": 5,
    "checked_bounds": [0, 1, 2, 3, 4, 5],
    "outcomes": [
      {
        "property_id": "inv.no_delete",
        "bound": 5,
        "result": "proved",
        "solver_query_ids": ["q-0001"]
      }
    ]
  },
  "artifacts": {
    "trace_hash": "f67ef6540ee251f6ca10fddfb58e85f29ce98f222f43b2c6b99f9280d6d07fc1",
    "state_hash_final": "5ea4b33267f0bc4439f2866a05f9f3375f2da0d80e0f6d8c7d2cb04345a4f9d1",
    "counterexamples": []
  },
  "hashes": {
    "decision_hash": "09eb2f721183a0fca4d35f2d9f7954d9db0ffc71dca0f45b1cdbf47e7649f9d2",
    "state_hash": "5ea4b33267f0bc4439f2866a05f9f3375f2da0d80e0f6d8c7d2cb04345a4f9d1",
    "report_hash": "fdbe4b8946d2f6f7f0d16362cc6df0d0fdf90b02da010de5266d145c1f7eb2e8"
  },
  "reproducibility": {
    "deterministic_replay_passed": true,
    "canonical_serialization": "JCS-RFC8785",
    "tool_versions": {
      "payments.approve": "1.0.2",
      "ledger.write": "3.4.1"
    },
    "nondeterminism_controls": [
      "stubbed_tool_outputs",
      "fixed_random_seed"
    ]
  },
  "signatures": {
    "signature_scheme": "ed25519",
    "key_id": "kid-prod-01",
    "report_signature": "MEQCIG4..."
  }
}
```

## Example B: Counterexample Payload (Normalized)
```json
{
  "counterexample_id": "cex-0001",
  "property": {
    "property_id": "temp.approve_implies_ledger",
    "property_kind": "temporal",
    "description": "ApprovePayment must eventually be followed by LedgerWrite"
  },
  "bound": 3,
  "witness_trace": [
    {
      "step_index": 0,
      "proposal_hash": "c4fcb4a73bf1e6710f3f7f8ee95f44d04ac8dd35ec89ad730e0f9b34bb9f53a3",
      "state_hash_before": "de2ba4e36f267f58f90ebf09e89ad5f5b69df1f8ecf892a6b5ea5e7f1cb8fb8f",
      "state_hash_after": "fba67d66268f5714af17df9044f5b4a4b49d9d67f8db62a8fd1082db7b87b4f4",
      "action_type": "ApprovePayment",
      "decision": "allowed"
    },
    {
      "step_index": 1,
      "proposal_hash": "045c8dd3852a16d3a2579c7776dcfc59366dfa7ca27f3c0f7f4e3206f5f744c2",
      "state_hash_before": "fba67d66268f5714af17df9044f5b4a4b49d9d67f8db62a8fd1082db7b87b4f4",
      "state_hash_after": "0c24720a9a12b2d10eb9d547f17b1882a07f2286cd2a490f49d84b7d6fe7c473",
      "action_type": "SendEmail",
      "decision": "allowed"
    }
  ],
  "violated_constraints": [
    {
      "constraint_id": "rule.payments.must_ledger_write",
      "constraint_type": "temporal",
      "message": "Obligation remained pending at bound 3"
    }
  ]
}
```

## Consumption Notes
- Phase 3 certificate tools verify hash chain parity using `hashes.decision_hash`, `hashes.state_hash`, and `hashes.report_hash`.
- Phase 3 forensic tooling rehydrates temporal progression from `temporal_monitor.transitions` and root-cause details from normalized `counterexamples`.
