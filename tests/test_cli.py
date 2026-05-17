from pathlib import Path

from typer.testing import CliRunner

from wdif.cli import app


runner = CliRunner()


def test_cli_analyze_json_sample_trace():
    result = runner.invoke(app, ["analyze", "examples/sample_trace.json", "--json"])

    assert result.exit_code == 0
    assert "AGENT_LOOP" in result.output
    assert "RETRIEVER_MISS" in result.output


def test_cli_writes_markdown_report(tmp_path: Path):
    report = tmp_path / "report.md"

    result = runner.invoke(app, ["analyze", "examples/sample_trace.json", "--report", str(report)])

    assert result.exit_code == 0
    assert report.exists()
    assert "WhyDidItFail Diagnostic Report" in report.read_text(encoding="utf-8")


def test_cli_batch_json():
    result = runner.invoke(app, ["batch", "examples", "--json"])

    assert result.exit_code == 0
    assert "sample_trace.json" in result.output
    assert "openinference_trace.json" in result.output


def test_cli_export_html(tmp_path: Path):
    output = tmp_path / "export.html"

    result = runner.invoke(app, ["export", "examples", "--output", str(output), "--workers", "1"])

    assert result.exit_code == 0
    assert output.exists()
    assert "WhyDidItFail Export" in output.read_text(encoding="utf-8")


def test_cli_tree_supports_jsonl_span_stream(tmp_path: Path):
    trace_file = tmp_path / "trace.jsonl"
    trace_file.write_text(
        '{"id":"child","trace_id":"t1","parent_id":"root","name":"child","attributes":{"openinference.span.kind":"TOOL"}}\n'
        '{"id":"root","trace_id":"t1","parent_id":null,"name":"root","attributes":{"openinference.span.kind":"CHAIN"}}\n',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["tree", str(trace_file)])

    assert result.exit_code == 0
    assert "root" in result.output
    assert "child" in result.output


def test_cli_stream_writes_report_for_jsonl(tmp_path: Path):
    trace_file = tmp_path / "trace.jsonl"
    report = tmp_path / "stream_report.md"
    trace_file.write_text(
        '{"id":"root","trace_id":"t1","parent_id":null,"name":"root","attributes":{"openinference.span.kind":"CHAIN"}}\n',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["stream", str(trace_file), "--report", str(report)])

    assert result.exit_code == 0
    assert report.exists()


def test_cli_stream_writes_dlq_for_malformed_jsonl(tmp_path: Path):
    trace_file = tmp_path / "dirty.jsonl"
    dlq = tmp_path / "dirty.corrupted.log"
    trace_file.write_text(
        '{"id":"root","trace_id":"t1","parent_id":null,"name":"root","attributes":{"openinference.span.kind":"CHAIN"}}\n'
        '{"id": "broken", "input": {"prompt": "unterminated\n',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["stream", str(trace_file), "--dlq", str(dlq), "--json"])

    assert result.exit_code == 0
    assert dlq.exists()
    assert "broken" in dlq.read_text(encoding="utf-8")


def test_cli_batch_staged_groups_split_logs(tmp_path: Path):
    trace_dir = tmp_path / "logs"
    trace_dir.mkdir()
    (trace_dir / "server_a.jsonl").write_text(
        '{"id":"child","trace_id":"split-1","parent_id":"root","name":"child","attributes":{"openinference.span.kind":"TOOL"}}\n',
        encoding="utf-8",
    )
    (trace_dir / "server_b.jsonl").write_text(
        '{"id":"root","trace_id":"split-1","parent_id":null,"name":"root","attributes":{"openinference.span.kind":"CHAIN"}}\n',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["batch", str(trace_dir), "--staged", "--json"])

    assert result.exit_code == 0
    assert '"span_count": 2' in result.output
