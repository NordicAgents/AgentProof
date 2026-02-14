# Specification Language

VAC DSL defines machine-checkable safety and governance rules.

## Syntax
Rule blocks are declarative and named:
```vac
invariant "no_delete_user" {
  forbid action.type == "DeleteUser"
}

precondition "email_requires_consent" {
  when action.type == "SendEmail"
  require state.memory.user.consent == true
}
```

## Grammar (Simplified)
```ebnf
spec         := { rule }
rule         := invariant | precondition | budget | infoflow | temporal
invariant    := "invariant" string "{" predicate "}"
precondition := "precondition" string "{" when predicate require predicate "}"
budget       := "budget" string "{" limit_expr "}"
infoflow     := "infoflow" string "{" flow_expr "}"
temporal     := "temporal" string "{" ltl_expr "}"
```

## Examples
- Invariant: forbid dangerous action families.
- Precondition: require explicit consent or approval marker.
- Budget: cap total cost or API calls.
- Info-flow: prevent SECRET -> public-network sink.
- Temporal: ensure approval precedes transfer.

## Compilation Model
1. Parse -> AST.
2. Type and symbol resolution.
3. Normalize predicates.
4. Compile to:
   - deterministic runtime evaluators
   - SMT constraints
   - temporal monitor automata

## Supported Rule Types
- Invariants
- Preconditions
- Budgets
- Info-flow rules
- Temporal rules

## Limitations
- Quantification over unbounded domains is unsupported.
- Temporal checking is runtime/incremental unless bounded model checking is requested.
- User-defined functions are restricted to pure, total helpers.
- Floating-point constraints are approximated unless explicitly modeled.
