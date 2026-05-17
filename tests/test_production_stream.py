from pathlib import Path

from generate_production_logs import build_chaos_logs
from wdif.engine import DiagnosticEngine
from wdif.models import FailureType
from wdif.parser import OpenInferenceParser


def test_jsonl_span_stream_groups_out_of_order_children(tmp_path: Path):
    trace_file = tmp_path / "trace.jsonl"
    trace_file.write_text(
        "\n".join(
            [
                '{"id":"child","trace_id":"t1","parent_id":"root","name":"child","attributes":{"openinference.span.kind":"TOOL"}}',
                '{"id":"root","trace_id":"t1","parent_id":null,"name":"root","attributes":{"openinference.span.kind":"CHAIN"}}',
            ]
        ),
        encoding="utf-8",
    )

    payloads = list(OpenInferenceParser().iter_trace_payloads(trace_file))
    roots = OpenInferenceParser().parse_file_payload(payloads[0])

    assert len(payloads) == 1
    assert roots[0].span_id == "root"
    assert roots[0].children[0].span_id == "child"


def test_generated_production_logs_trigger_expected_failures(tmp_path: Path):
    trace_file = tmp_path / "production_traces_dump.jsonl"
    build_chaos_logs(trace_file)

    parser = OpenInferenceParser()
    diagnostics = []
    for payload in parser.iter_trace_payloads(trace_file):
        diagnostics.extend(DiagnosticEngine().analyze(parser.parse_file_payload(payload)))

    failure_types = {diagnostic.failure_type for diagnostic in diagnostics}

    assert FailureType.AGENT_LOOP in failure_types
    assert FailureType.LOST_IN_THE_MIDDLE in failure_types
