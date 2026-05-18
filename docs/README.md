# WDIF Technical Docs

This directory documents the engineering contracts behind WDIF. The goal is to make every diagnostic explainable, reproducible, and reviewable without depending on an LLM judge.

## Start Here

- [Deterministic Replay Architecture](deterministic-replay.md)
- [Causal Propagation Model](causal-propagation.md)
- [Replay Demo](replay-demo.md)
- [Open Research Problems](research-frontiers.md)
- [Release and Versioning Strategy](versioning.md)

## Core Philosophy

- Deterministic over probabilistic when a structural signal is available.
- Evidence over telemetry: traces are raw material, not the final answer.
- Replayable over ephemeral: every RCA result should be reconstructible later.
- Causal graphs over flat metrics: incidents propagate across spans and subsystems.
- Local-first infrastructure: diagnostics should work without API calls or cloud control planes.
- Governance-aware reliability: policy exits, manifests, and evidence hashes belong in the core path.

## Documentation Standards

Technical docs should describe:

- what the subsystem guarantees,
- what it deliberately does not guarantee,
- how failures degrade,
- how replay correctness is preserved,
- which tests prove the contract.
