from wdif.config import load_config
from wdif.engine import DiagnosticEngine
from wdif.models import FailureType, SpanType, TraceSpan


def test_load_yaml_config_and_policy_exit(tmp_path):
    config_file = tmp_path / "wdif.yaml"
    config_file.write_text(
        """
tokenizer:
  provider: regex
  name: local
exit_codes:
  CRITICAL: 1
  WARNING: 0
heuristics:
  AGENT_LOOP:
    severity: WARNING
    repeated_call_threshold: 2
""",
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.tokenizer.provider == "regex"
    assert config.policy_for("AGENT_LOOP").severity == "WARNING"
    assert config.exit_code_for({"CRITICAL"}) == 1


def test_config_remaps_tree_diagnostic_severity():
    root = TraceSpan(
        span_id="root",
        parent_id=None,
        name="agent",
        span_type=SpanType.AGENT,
        start_time_ms=0,
        end_time_ms=10,
    )
    root.children = [
        TraceSpan(
            span_id=f"tool_{idx}",
            parent_id="root",
            name="lookup",
            span_type=SpanType.TOOL,
            start_time_ms=idx,
            end_time_ms=idx + 1,
            input_data={"query": "same"},
        )
        for idx in range(4)
    ]

    from wdif.config.engine import HeuristicPolicy, WdifConfig

    config = WdifConfig(
        heuristics={
            "AGENT_LOOP": HeuristicPolicy(severity="WARNING", options={"repeated_call_threshold": 4})
        }
    )
    diagnostics = DiagnosticEngine(config=config).analyze([root])

    assert diagnostics[0].failure_type == FailureType.AGENT_LOOP
    assert diagnostics[0].severity == "WARNING"
