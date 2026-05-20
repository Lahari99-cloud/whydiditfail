from wdif.models import SpanType
from wdif.parser import OpenInferenceParser


def test_parser_builds_tree_from_flat_spans():
    roots = OpenInferenceParser().parse_raw_spans(
        [
            {
                "span_id": "root",
                "name": "pipeline",
                "attributes": {"openinference.span.kind": "CHAIN"},
                "start_time_ms": 1,
                "end_time_ms": 5,
            },
            {
                "span_id": "child",
                "parent_id": "root",
                "name": "llm",
                "attributes": {"openinference.span.kind": "LLM"},
                "start_time_ms": 2,
                "end_time_ms": 4,
            },
        ]
    )

    assert len(roots) == 1
    assert roots[0].span_type == SpanType.CHAIN
    assert roots[0].children[0].span_id == "child"
    assert roots[0].children[0].span_type == SpanType.LLM


def test_parser_flattens_otlp_resource_spans_and_hydrates_io():
    roots = OpenInferenceParser().parse_file_payload(
        {
            "resourceSpans": [
                {
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "spanId": "llm",
                                    "name": "answer",
                                    "attributes": [
                                        {
                                            "key": "openinference.span.kind",
                                            "value": {"stringValue": "LLM"},
                                        },
                                        {
                                            "key": "input.value",
                                            "value": {"stringValue": "question"},
                                        },
                                        {
                                            "key": "output.value",
                                            "value": {"stringValue": "answer"},
                                        },
                                    ],
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    )

    assert roots[0].span_id == "llm"
    assert roots[0].span_type == SpanType.LLM
    assert roots[0].input_data["value"] == "question"
    assert roots[0].output_data["value"] == "answer"


def test_observability_fixtures_parse_with_source_metadata():
    parser = OpenInferenceParser()

    expectations = {
        "examples/langsmith_trace.json": ("ls-root", "langsmith.project_name"),
        "examples/phoenix_trace.json": ("px-root", "phoenix.project_name"),
        "examples/opik_trace.json": ("opik-root", "opik.project_name"),
    }

    for fixture, (root_id, metadata_key) in expectations.items():
        roots = list(parser.iter_trace_payloads(fixture))
        parsed = parser.parse_file_payload(roots[0])

        assert parsed[0].span_id == root_id
        assert metadata_key in parsed[0].attributes
        assert parsed[0].children
