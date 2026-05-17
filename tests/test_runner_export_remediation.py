import json

from wdif.core.runner import run_batch
from wdif.export import render_aggregate_html
from wdif.parser import OpenInferenceParser
from wdif.remediation import build_context_reorder_patch


def test_run_batch_returns_trace_results():
    result = run_batch(
        [
            __import__("pathlib").Path("examples/sample_trace.json"),
            __import__("pathlib").Path("examples/openinference_trace.json"),
        ],
        workers=1,
    )

    assert len(result.results) == 2
    assert result.diagnostic_count >= 2


def test_parser_streams_jsonl(tmp_path):
    jsonl = tmp_path / "traces.jsonl"
    payload = {"spans": [{"span_id": "root", "name": "root"}]}
    jsonl.write_text(json.dumps(payload) + "\n" + json.dumps(payload), encoding="utf-8")

    items = list(OpenInferenceParser().iter_trace_payloads(jsonl))

    assert len(items) == 2


def test_context_reorder_patch_generates_unified_diff():
    patch = build_context_reorder_patch("intro\nCRITICAL_FACT\nquestion", "CRITICAL_FACT")

    assert patch is not None
    assert "--- prompt_template.before" in patch.diff
    assert "+++ prompt_template.after" in patch.diff


def test_aggregate_html_contains_taxonomy():
    result = run_batch([__import__("pathlib").Path("examples/sample_trace.json")], workers=1)

    html = render_aggregate_html(result.results)

    assert "WhyDidItFail Export" in html
    assert "AGENT_LOOP" in html
