"""Evidence snapshot and replay engine for time-travel debugging (Phase 2)."""

from wdif.replay.engine import (
    EvidenceSnapshot,
    EvidenceSnapshotEngine,
    ReplayResult,
    ReplayEngine,
    ReplayPolicy,
    diff_snapshots,
)

__all__ = [
    "EvidenceSnapshot",
    "EvidenceSnapshotEngine",
    "ReplayResult",
    "ReplayEngine",
    "ReplayPolicy",
    "diff_snapshots",
]
