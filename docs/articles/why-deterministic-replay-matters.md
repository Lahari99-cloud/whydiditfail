# Why Deterministic Replay Matters for Agentic AI Reliability

Most AI reliability tooling starts with telemetry. It collects traces, token counts, latency, costs, model names, prompts, tool calls, retriever results, and final responses.

That is necessary, but it is not sufficient.

Telemetry tells you what happened. A reliability system also needs to prove that its explanation can be reconstructed later.

That is the reason WDIF treats deterministic replay as a first-class primitive.

## Telemetry Is Not Evidence Yet

Raw traces are noisy. They can arrive out of order, contain malformed rows, miss parent spans, duplicate tool calls, or mix several model providers inside one agent trajectory.

Even when trace collection is correct, a dashboard usually leaves the engineer with the hardest part:

```text
Why did this system fail structurally?
```

For production AI systems, the failure is rarely isolated. A retriever miss can lead to planner retries. Planner retries can duplicate context. Context duplication can push evidence into a weak token position. The final answer may look like a model-quality issue, while the real upstream cause was retrieval or orchestration.

This is why WDIF focuses on deterministic causal diagnostics instead of black-box judging.

## Replay Correctness

Replay correctness is stricter than storing a span tree.

A trustworthy replay must preserve:

- the normalized span tree,
- diagnostic outputs,
- ranking order,
- causal propagation metadata,
- configuration,
- tokenizer assumptions,
- normalization assumptions,
- dependency and platform provenance,
- snapshot integrity.

In WDIF, a replay is considered valid only when:

```json
{
  "matches_original": true,
  "snapshot_hash_valid": true,
  "determinism_manifest_valid": true,
  "diagnostic_diff": {
    "changed_count": 0
  }
}
```

That means the evidence file was not modified, the replay environment still matches the captured assumptions, and the RCA output reproduced exactly.

## Why Manifests Matter

A replay system can drift silently.

Tokenizers change. Ranking logic changes. Normalization rules change. Dependency versions change. A trace that produced one RCA result last month can produce a different result today, even if the raw spans are identical.

WDIF snapshots include a determinism manifest so this drift is visible. The manifest captures hashes for the span tree, diagnostics, config, normalization, and ranking. It also captures environment and dependency provenance.

That is the difference between "we stored the trace" and "we can audit the diagnostic."

## Causal Reproducibility

Agentic systems fail through trajectories:

```text
retriever miss
  -> ungrounded answer
  -> policy gate failure
```

WDIF attaches causal propagation metadata to diagnostics so the replayed output can verify not only that the same failure labels occurred, but that the same structural explanation survived reconstruction.

This matters because enterprise incident reviews care about upstream cause, not only downstream symptom.

## Governance Lineage

Reliability evidence becomes more valuable when it can be used in CI/CD and governance workflows.

Replayable snapshots support:

- pull request regression checks,
- deterministic incident review,
- audit trails,
- policy exit verification,
- before/after remediation comparison.

This is why WDIF exposes:

```bash
wdif snapshot trace.json --output trace.wdif
wdif replay trace.wdif
wdif diff before.wdif after.wdif
```

The goal is not to replace observability platforms. The goal is to make AI failure explanations reproducible enough to trust.

## The Larger Direction

Agentic AI reliability will need more than metrics. It will need evidence systems: tools that can reconstruct how a failure propagated, explain which assumptions were used, and prove whether the explanation still holds later.

Deterministic replay is one step toward that.

WDIF starts from a simple position:

```text
If a diagnostic cannot be replayed, it should not be treated as evidence.
```
