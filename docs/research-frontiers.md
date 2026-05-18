# Open Research Problems

WDIF intentionally avoids pretending that every hard production RCA problem is solved. The remaining frontier is distributed, causal, and governance-linked reliability.

## Distributed Causal Correctness

Production agent systems are asynchronous. Spans can arrive late, clocks can drift, and parent/child relationships can be incomplete. Future WDIF versions need logical ordering metadata, skew-tolerant reconciliation, and partial-trace confidence degradation.

## Graph Explosion Control

As causal propagation chains grow, naive breadth-first analysis can become noisy and expensive. WDIF needs graph pruning, dominance filtering, path suppression, and branch collapsing so RCA output remains usable.

## Adaptive Propagation Priors

Hardcoded causal priors are useful for initial deterministic behavior, but organizations have different architectures and failure patterns. Long-term reliability memory should learn which propagation paths recur and which remediations actually reduce downstream failures.

## Intervention-Aware RCA

The next step after diagnosis is controlled intervention:

- stop planner loops,
- quarantine broken tools,
- force retrieval refresh,
- block unsafe context propagation,
- record whether remediation improved replay outcomes.

## Replay Determinism Under Async Orchestration

Replay equality is tractable for local snapshots. Distributed replay is harder because event ordering may be partially known. WDIF should make uncertainty explicit instead of over-claiming causality.

## Governance-Linked RCA

Enterprise incidents often combine technical failure with policy failure. Future RCA should connect policy bypasses, unsafe retrieval, hallucinated synthesis, and compliance events into one auditable evidence chain.
