# Example Specs

## 1) Basic Safety Spec
```vac
invariant "no_delete_user" { forbid action.type == "DeleteUser" }
budget "max_calls" { calls <= 20 }
```

## 2) Financial Agent Spec
```vac
precondition "transfer_needs_approval" {
  when action.type == "TransferFunds"
  require state.memory.approved == true
}
budget "daily_limit" { cost <= 1000 }
temporal "ledger_after_transfer" { G(TransferFunds -> F LedgerWrite) }
```

## 3) Data Privacy Spec
```vac
infoflow "block_secret_to_public_net" {
  deny label("SECRET") -> sink("public_network")
}
invariant "pii_export_requires_token" {
  when action.type == "ExportPII"
  require state.memory.export_token_valid == true
}
```

## 4) Multi-Step Workflow Spec
```vac
temporal "approve_before_execute" { G(ExecuteJob -> P ApproveJob) }
temporal "eventual_close" { G(OpenTicket -> F CloseTicket) }
budget "retry_cap" { retries <= 3 }
```
