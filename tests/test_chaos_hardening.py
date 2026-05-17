from pathlib import Path

from generate_chaos_logs import build_parser_chaos_logs
from wdif.core.runner import run_staged_batch
from wdif.engine import DiagnosticEngine
from wdif.ingestion import DeadLetterQueue, TraceStagingBuffer, read_json_stream
from wdif.models import FailureType
from wdif.parser import OpenInferenceParser


def test_malformed_jsonl_line_goes_to_dlq_and_valid_spans_continue(tmp_path: Path):
    trace_file = tmp_path / "dirty.jsonl"
    dlq_file = tmp_path / "dirty.corrupted.log"
    build_parser_chaos_logs(trace_file)

    result = read_json_stream(trace_file, DeadLetterQueue(dlq_file))

    assert len(result.dead_letters) == 1
    assert dlq_file.exists()
    assert len(result.payloads) == 2


def test_context_bomb_is_estimated_not_crashed(tmp_path: Path):
    trace_file = tmp_path / "dirty.jsonl"
    build_parser_chaos_logs(trace_file)
    read_result = read_json_stream(trace_file)
    staging = TraceStagingBuffer()
    staging.extend(read_result.payloads)

    diagnostics = []
    parser = OpenInferenceParser()
    for payload in staging.flush():
        diagnostics.extend(DiagnosticEngine().analyze(parser.parse_file_payload(payload)))

    context = next(item for item in diagnostics if item.failure_type == FailureType.CONTEXT_STUFFING)
    attention = next(item for item in diagnostics if item.failure_type == FailureType.LOST_IN_THE_MIDDLE)

    assert context.metadata["token_count_mode"] == "estimated"
    assert attention.metadata["token_count_mode"] == "estimated"


def test_split_logs_are_staged_across_files(tmp_path: Path):
    child = tmp_path / "traces_server_a.jsonl"
    parent = tmp_path / "traces_server_b.jsonl"
    child.write_text(
        '{"id":"child","trace_id":"split-1","parent_id":"root","name":"child","attributes":{"openinference.span.kind":"TOOL"}}\n',
        encoding="utf-8",
    )
    parent.write_text(
        '{"id":"root","trace_id":"split-1","parent_id":null,"name":"root","attributes":{"openinference.span.kind":"CHAIN"}}\n',
        encoding="utf-8",
    )

    result = run_staged_batch([child, parent])

    assert result.span_count == 2


def test_staging_buffer_spills_oversized_trace_to_disk(tmp_path: Path):
    spill = tmp_path / "trace_spill.jsonl"
    staging = TraceStagingBuffer(max_spans_per_trace=2, spill_path=spill)

    staging.add({"id": "span-1", "trace_id": "huge-trace", "name": "tool"})
    staging.add({"id": "span-2", "trace_id": "huge-trace", "name": "tool"})

    assert staging.spilled_trace_count == 1
    assert spill.exists()

    payloads = staging.flush()

    assert payloads == [
        {
            "spans": [
                {"id": "span-1", "trace_id": "huge-trace", "name": "tool"},
                {"id": "span-2", "trace_id": "huge-trace", "name": "tool"},
            ]
        }
    ]
    assert not spill.exists()
