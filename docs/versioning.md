# Release and Versioning Strategy

WDIF uses version numbers to communicate reliability contracts, not just feature count.

## Version Goals

### v0.1: Deterministic Replay Foundation

- `.wdif` evidence snapshots
- snapshot integrity hashes
- determinism manifests
- deterministic replay verification
- snapshot diffing

### v0.2: Distributed Causality Foundation

- logical ordering metadata
- clock-skew tolerant trace reconciliation
- partial-trace confidence degradation
- causal graph pruning controls

### v0.3: Adaptive Reliability Memory

- remediation outcome tracking
- learned propagation priors
- recurring failure pattern detection
- topology-aware RCA weighting

### v1.0: Stable Evidence Contract

- documented snapshot schema compatibility
- stable CLI contracts
- stable diagnostic event schema
- reproducible benchmark suite
- published package release workflow

## Compatibility Rules

- Patch releases should not change snapshot semantics.
- Minor releases may add fields but should preserve older snapshot replay.
- Breaking snapshot schema changes require a migration note.
- CLI output used by CI should remain stable across patch releases.
