# Contributing to WDIF

WDIF is deterministic causal reliability infrastructure. Contributions should strengthen reproducibility, evidence quality, and operational clarity.

## Infrastructure Contribution Philosophy

- Deterministic behavior is required for core RCA paths.
- Replay correctness is mandatory for changes that affect diagnostics, ranking, normalization, or causal propagation.
- Diagnostics must be reproducible from trace evidence.
- WDIF should not use LLM-generated RCA in the core decision path.
- Causal edges must be explainable from trace structure, diagnostic metadata, or documented rules.
- Unknown or weak evidence should degrade confidence instead of producing unsupported certainty.
- Security redaction belongs at serialization/output boundaries, not before diagnostic analysis.

## Required Checks

Before opening a PR:

```bash
python -m pytest -q
python -m compileall wdif tests
```

If your change affects replay, also run:

```bash
wdif snapshot examples/openinference_trace.json --output reports/openinference_trace.wdif --json
wdif replay reports/openinference_trace.wdif --json
wdif diff reports/openinference_trace.wdif reports/openinference_trace.wdif --json
```

Replay should preserve:

- snapshot hash validity,
- determinism manifest validity,
- original-vs-replay diagnostic equality,
- zero diff for identical snapshots.

## Diagnostic Rules

New diagnostics should include:

- a specific failure type,
- severity routing support,
- evidence metadata,
- confidence or uncertainty metadata where appropriate,
- a practical suggested fix,
- tests covering positive and negative cases.

## Causal Rules

New causal propagation rules should document:

- upstream trigger,
- downstream effect,
- required evidence,
- abstention conditions,
- confidence behavior,
- graph explosion risk.

## Documentation

When a contribution changes architecture or operator behavior, update the relevant docs in `docs/` and the README if the first-run experience changes.
