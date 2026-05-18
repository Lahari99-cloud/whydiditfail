import json
from pathlib import Path

from typer.testing import CliRunner

from wdif.cli import app
from wdif.replay import EvidenceSnapshotEngine, ReplayEngine, diff_snapshots
from wdif.replay.engine import validate_determinism_manifest


runner = CliRunner()


def test_snapshot_replay_preserves_diagnostics(tmp_path: Path):
    trace_file = tmp_path / "trace.json"
    snapshot_file = tmp_path / "trace.wdif"
    trace_file.write_text(
        json.dumps(
            {
                "spans": [
                    {
                        "id": "retriever",
                        "trace_id": "replay-1",
                        "name": "search",
                        "attributes": {"openinference.span.kind": "RETRIEVER"},
                        "output": {"documents": []},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    snapshot = EvidenceSnapshotEngine().capture_trace_file(trace_file)
    EvidenceSnapshotEngine.save_snapshot(snapshot, snapshot_file)
    loaded = EvidenceSnapshotEngine.load_snapshot(snapshot_file)
    result = ReplayEngine().replay(loaded)

    assert loaded.validate_hash()
    assert validate_determinism_manifest(loaded)["valid"]
    assert result.matches_original
    assert result.determinism_manifest_valid
    assert result.diagnostic_diff["changed_count"] == 0
    assert result.original_diagnostics == result.replay_diagnostics


def test_snapshot_hash_detects_tampering(tmp_path: Path):
    trace_file = tmp_path / "trace.json"
    snapshot_file = tmp_path / "trace.wdif"
    trace_file.write_text(
        json.dumps(
            {
                "spans": [
                    {
                        "id": "retriever",
                        "trace_id": "replay-2",
                        "name": "search",
                        "attributes": {"openinference.span.kind": "RETRIEVER"},
                        "output": {"documents": []},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    snapshot = EvidenceSnapshotEngine().capture_trace_file(trace_file)
    EvidenceSnapshotEngine.save_snapshot(snapshot, snapshot_file)

    data = json.loads(snapshot_file.read_text(encoding="utf-8"))
    data["roots"][0]["name"] = "tampered"
    snapshot_file.write_text(json.dumps(data), encoding="utf-8")

    loaded = EvidenceSnapshotEngine.load_snapshot(snapshot_file)
    result = ReplayEngine().replay(loaded)

    assert not loaded.validate_hash()
    assert not result.matches_original
    assert not result.snapshot_hash_valid
    assert not result.determinism_manifest_valid


def test_determinism_manifest_detects_diagnostic_drift(tmp_path: Path):
    trace_file = tmp_path / "trace.json"
    snapshot_file = tmp_path / "trace.wdif"
    trace_file.write_text(
        json.dumps(
            {
                "spans": [
                    {
                        "id": "retriever",
                        "trace_id": "replay-3",
                        "name": "search",
                        "attributes": {"openinference.span.kind": "RETRIEVER"},
                        "output": {"documents": []},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    snapshot = EvidenceSnapshotEngine().capture_trace_file(trace_file)
    EvidenceSnapshotEngine.save_snapshot(snapshot, snapshot_file)

    data = json.loads(snapshot_file.read_text(encoding="utf-8"))
    data["diagnostics"][0]["confidence_score"] = 0.123
    snapshot_file.write_text(json.dumps(data), encoding="utf-8")

    loaded = EvidenceSnapshotEngine.load_snapshot(snapshot_file)
    validation = validate_determinism_manifest(loaded)

    assert not validation["valid"]
    assert "diagnostics_hash" in validation["mismatches"]


def test_snapshot_diff_reports_new_failure(tmp_path: Path):
    before_trace = tmp_path / "before.json"
    after_trace = tmp_path / "after.json"
    before_trace.write_text(
        json.dumps({"spans": [{"id": "root", "name": "root", "attributes": {"openinference.span.kind": "CHAIN"}}]}),
        encoding="utf-8",
    )
    after_trace.write_text(
        json.dumps(
            {
                "spans": [
                    {
                        "id": "retriever",
                        "name": "search",
                        "attributes": {"openinference.span.kind": "RETRIEVER"},
                        "output": {"documents": []},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    before = EvidenceSnapshotEngine().capture_trace_file(before_trace)
    after = EvidenceSnapshotEngine().capture_trace_file(after_trace)
    diff = diff_snapshots(before, after)

    assert diff["diagnostic_diff"]["added"] == ["|retriever|RETRIEVER_MISS"]
    assert diff["diagnostic_diff"]["changed_count"] == 1
    assert diff["snapshot_a_manifest_valid"]
    assert diff["snapshot_b_manifest_valid"]


def test_snapshot_replay_cli_roundtrip(tmp_path: Path):
    trace_file = tmp_path / "trace.json"
    snapshot_file = tmp_path / "trace.wdif"
    trace_file.write_text(
        json.dumps(
            {
                "spans": [
                    {
                        "id": "retriever",
                        "trace_id": "replay-cli",
                        "name": "search",
                        "attributes": {"openinference.span.kind": "RETRIEVER"},
                        "output": {"documents": []},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    snapshot_result = runner.invoke(
        app,
        ["snapshot", str(trace_file), "--output", str(snapshot_file), "--json"],
    )
    replay_result = runner.invoke(app, ["replay", str(snapshot_file), "--json"])

    assert snapshot_result.exit_code == 0
    assert replay_result.exit_code == 0
    assert '"matches_original": true' in replay_result.output
    assert '"determinism_manifest_valid": true' in replay_result.output
