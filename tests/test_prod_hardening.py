from pathlib import Path

from typer.testing import CliRunner

from wdif.cli import app
from wdif.config import ConfigError, load_config
from wdif.engine import DiagnosticEngine
from wdif.heuristics.attention import LostInTheMiddleHeuristic
from wdif.models import FailureType
from wdif.parser import OpenInferenceParser
from wdif.security import sanitize_value


runner = CliRunner()


def test_trace_id_is_preserved_in_diagnostics():
    roots = OpenInferenceParser().parse_raw_spans(
        [
            {
                "id": "retriever",
                "trace_id": "trace-prod-1",
                "name": "search",
                "attributes": {"openinference.span.kind": "RETRIEVER"},
                "output": {"documents": []},
            }
        ]
    )

    diagnostics = DiagnosticEngine().analyze(roots)

    assert diagnostics[0].trace_id == "trace-prod-1"
    assert diagnostics[0].to_dict()["trace_id"] == "trace-prod-1"


def test_orphaned_span_tree_is_reported():
    roots = OpenInferenceParser().parse_raw_spans(
        [
            {
                "id": "child",
                "trace_id": "trace-orphan",
                "parent_id": "missing-parent",
                "name": "child",
                "attributes": {"openinference.span.kind": "TOOL"},
            }
        ]
    )

    diagnostics = DiagnosticEngine().analyze(roots)

    assert any(item.failure_type == FailureType.ORPHANED_SPAN_TREE for item in diagnostics)


def test_invalid_config_fails_fast(tmp_path: Path):
    config = tmp_path / "wdif.yaml"
    config.write_text(
        """
tokenizer:
  provider: madeup
heuristics:
  LOST_IN_THE_MIDDLE:
    severity: PANIC
""",
        encoding="utf-8",
    )

    try:
        load_config(config)
    except ConfigError as exc:
        assert "Unsupported tokenizer" in str(exc)
    else:
        raise AssertionError("Expected ConfigError")


def test_sanitize_redacts_secrets_and_truncates():
    sanitized = sanitize_value(
        {
            "authorization": "Bearer abcdefghijklmnopqrstuvwxyz1234567890",
            "prompt_tokens": 120061,
            "token_count_mode": "estimated",
            "email": "person@example.com",
            "body": "hello world " * 200,
        },
        max_string_chars=20,
    )

    assert sanitized["authorization"] == "[REDACTED]"
    assert sanitized["prompt_tokens"] == 120061
    assert sanitized["token_count_mode"] == "estimated"
    assert sanitized["email"] == "[REDACTED_EMAIL]"
    assert sanitized["body"].endswith("[TRUNCATED]")


def test_stream_json_exposes_dead_letter_count(tmp_path: Path):
    trace_file = tmp_path / "dirty.jsonl"
    dlq = tmp_path / "dirty.corrupted.log"
    trace_file.write_text(
        '{"id":"root","trace_id":"t1","name":"root","attributes":{"openinference.span.kind":"CHAIN"}}\n'
        '{"id": "broken", "input": {"prompt": "unterminated\n',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["stream", str(trace_file), "--dlq", str(dlq), "--json"])

    assert result.exit_code == 0
    assert '"dead_letter_count": 1' in result.output


def test_redaction_does_not_mutate_heuristic_input():
    secret_doc = "SECRET_PORT_VALUE_ABCDEF1234567890 = 9921"
    prompt = ("prefix context " * 500) + secret_doc + (" suffix context " * 500)
    roots = OpenInferenceParser().parse_raw_spans(
        [
            {
                "id": "llm",
                "trace_id": "trace-secret",
                "name": "llm",
                "attributes": {
                    "openinference.span.kind": "LLM",
                    "openinference.retrieval.documents": [
                        {"id": "doc_secret", "content": secret_doc}
                    ],
                },
                "input": {"prompts": [prompt]},
            }
        ]
    )

    diagnostic = LostInTheMiddleHeuristic(min_prompt_tokens=100).analyze_span(roots[0])

    assert diagnostic is not None
    assert diagnostic.metadata["chunk_excerpt"] == secret_doc
    assert diagnostic.to_dict()["metadata"]["chunk_excerpt"] == "[REDACTED_TOKEN] = 9921"


def test_dead_letters_can_drive_policy_exit(tmp_path: Path):
    trace_file = tmp_path / "dirty.jsonl"
    dlq = tmp_path / "dirty.corrupted.log"
    config = tmp_path / "wdif.yaml"
    trace_file.write_text(
        '{"id":"root","trace_id":"t1","name":"root","attributes":{"openinference.span.kind":"CHAIN"}}\n'
        '{"id": "broken", "input": {"prompt": "unterminated\n',
        encoding="utf-8",
    )
    config.write_text(
        """
exit_codes:
  CRITICAL: 2
  WARNING: 1
ingestion:
  dead_letter_severity: WARNING
  fail_on_dead_letters: true
""",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["stream", str(trace_file), "--config", str(config), "--dlq", str(dlq), "--policy-exit"],
    )

    assert result.exit_code == 1
