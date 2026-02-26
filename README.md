# Agentproof

Static graph verification for LangGraph agents. Prove safety properties on your agent's workflow graph **before deployment** — no runtime overhead, no gatekeeping layer.

## Why

Every existing "safe agent" tool is a runtime gatekeeper: intercept calls, check a policy, maybe log an audit trail. That approach duplicates what the orchestration framework already does and adds latency to every step.

Agentproof takes a different path. It treats a LangGraph `StateGraph` as a formal object — a directed graph with typed edges and tool-binding nodes — and runs static analysis on the topology itself. If a property holds on the graph, it holds for every possible execution.

## Status

Early development. The LTL-to-DFA monitor compiler (carried over from the previous iteration) is functional. Graph analysis primitives are next.

## Install

```bash
pip install -e ".[dev]"
```

```python
import agentproof
print(agentproof.__version__)  # 0.2.0
```

## Project Structure

```
src/agentproof/
├── __init__.py
└── monitor/
    ├── __init__.py
    └── ltl.py          # LTL-to-DFA temporal monitor compiler
```

## License

MIT
