# Replay Demo

The strongest WDIF demo is a terminal replay, not a dashboard.

![WDIF replay terminal demo](assets/replay-demo.svg)

## Commands

Create an immutable evidence snapshot:

```bash
wdif snapshot examples/openinference_trace.json --output reports/openinference_trace.wdif --json
```

Replay the snapshot and verify RCA equality:

```bash
wdif replay reports/openinference_trace.wdif --json
```

Expected replay invariants:

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

Compare two snapshots for regression analysis:

```bash
wdif diff reports/before.wdif reports/after.wdif --json
```

## Recording Guidance

A short demo recording should show:

1. `wdif analyze` finding a structural failure.
2. `wdif snapshot` writing the `.wdif` evidence file.
3. `wdif replay` proving deterministic RCA equality.
4. `wdif diff` comparing two snapshots.

Keep the demo under 90 seconds. The point is reproducible evidence, not UI polish.
