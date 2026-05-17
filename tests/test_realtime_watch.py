import json
from pathlib import Path

from typer.testing import CliRunner

from wdif.cli import app
from wdif.config.engine import IngestionPolicy, WdifConfig
from wdif.models import FailureType
from wdif.realtime import LiveTraceWatcher, watch_file


runner = CliRunner()


def test_watch_file_tails_appended_jsonl_and_flushes_trace(tmp_path: Path):
    trace_file = tmp_path / "live.jsonl"
    dlq = tmp_path / "live.corrupted.log"
    trace_file.write_text(
        json.dumps(
            {
                "id": "retriever",
                "trace_id": "live-1",
                "parent_id": "root",
                "name": "retriever",
                "attributes": {"openinference.span.kind": "RETRIEVER"},
                "output": {"documents": []},
            }
        )
        + "\n"
        + '{"id": "broken", "input": {"prompt": "unterminated\n'
        + json.dumps(
            {
                "id": "root",
                "trace_id": "live-1",
                "parent_id": None,
                "name": "root",
                "attributes": {"openinference.span.kind": "CHAIN"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    stats = watch_file(
        trace_file,
        dlq_path=dlq,
        flush_after_seconds=0.2,
        poll_interval_seconds=0.05,
        max_seconds=0.4,
        start_at_end=False,
    )

    assert stats.lines_read == 3
    assert stats.dead_letter_count == 1
    assert dlq.exists()
    assert any(diagnostic.failure_type == FailureType.RETRIEVER_MISS for diagnostic in stats.diagnostics)


def test_watch_cli_outputs_json_summary(tmp_path: Path):
    trace_file = tmp_path / "live.jsonl"
    trace_file.write_text(
        '{"id":"root","trace_id":"live-cli","name":"root","attributes":{"openinference.span.kind":"CHAIN"}}\n',
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "watch",
            str(trace_file),
            "--max-seconds",
            "0.2",
            "--flush-after",
            "0.1",
            "--poll-interval",
            "0.05",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert '"lines_read": 1' in result.output
    assert '"traces_flushed": 1' in result.output


def test_watch_evicts_trace_that_exceeds_span_bound(tmp_path: Path):
    trace_file = tmp_path / "live.jsonl"
    trace_file.write_text("", encoding="utf-8")
    config = WdifConfig(ingestion=IngestionPolicy(max_trace_spans=2))
    watcher = LiveTraceWatcher(
        trace_file,
        config=config,
        flush_after_seconds=30.0,
        poll_interval_seconds=0.05,
    )

    trace_file.write_text(
        json.dumps({"id": "span-1", "trace_id": "oversized", "name": "tool"})
        + "\n"
        + json.dumps({"id": "span-2", "trace_id": "oversized", "name": "tool"})
        + "\n",
        encoding="utf-8",
    )
    stats = watcher.watch(max_seconds=0.15)

    assert stats.traces_evicted == 1
    assert stats.traces_flushed == 2
