# Causal Propagation Model

WDIF treats production AI failures as trajectories, not isolated events. A retriever miss can lead to an ungrounded answer. A tool error can trigger planner retries. Repeated retries can stuff context and cause downstream attention failures.

## Causal Edge Contract

A causal edge should be emitted only when WDIF can explain the structural relationship between two findings.

Each propagated diagnostic should expose:

- causal role,
- upstream failure types,
- causal chain,
- propagation depth,
- confidence or uncertainty metadata when available.

## Example

```json
{
  "failure_type": "UNGROUNDED_ANSWER",
  "metadata": {
    "causal_role": "downstream_effect",
    "causal_upstream_failure_types": ["RETRIEVER_MISS"],
    "causal_chain": [
      "RETRIEVER_MISS@retriever",
      "UNGROUNDED_ANSWER@llm"
    ],
    "causal_propagation_depth": 1
  }
}
```

## Design Rules

- Causal chains must be explainable from trace structure or diagnostic metadata.
- WDIF should prefer abstention over unsupported causality.
- Propagation depth should remain bounded to avoid noisy RCA explosions.
- Causal ranking should make upstream root causes easier to see than downstream symptoms.

## Current Scope

The current model focuses on deterministic structural relationships, including:

- retriever failures propagating into ungrounded answers,
- tool failures contributing to agent retry patterns,
- context failures contributing to LLM response failures,
- orphaned spans degrading trace confidence.

## Future Work

Distributed traces introduce clock skew, partial ordering, missing spans, and delayed telemetry. Those require logical ordering metadata before WDIF can make stronger distributed causality claims.
