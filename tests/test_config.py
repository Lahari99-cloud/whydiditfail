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


def test_loads_ingestion_memory_bounds(tmp_path):
    config_file = tmp_path / "wdif.yaml"
    config_file.write_text(
        """
ingestion:
  max_active_traces: 25
  max_trace_spans: 100
  max_trace_age_seconds: 30
""",
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.ingestion.max_active_traces == 25
    assert config.ingestion.max_trace_spans == 100
    assert config.ingestion.max_trace_age_seconds == 30


def test_loads_tokenizer_routes_from_yaml(tmp_path):
    config_file = tmp_path / "wdif.yaml"
    config_file.write_text(
        """
tokenizer:
  provider: tiktoken
  name: cl100k_base
tokenizer_routes:
  - match: llama
    provider: regex
    name: llama-regex-local
""",
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.tokenizer_routes[0].match == "llama"
    assert config.tokenizer_routes[0].provider == "regex"


def test_loads_extraction_mappings_from_yaml(tmp_path):
    config_file = tmp_path / "wdif.yaml"
    config_file.write_text(
        """
extraction_mappings:
  prompt: "$.attributes['gen_ai.prompt_text']"
  documents:
    - "$.attributes['custom_retriever.chunks']"
""",
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.extraction_mappings.prompt == ["$.attributes['gen_ai.prompt_text']"]
    assert config.extraction_mappings.documents == ["$.attributes['custom_retriever.chunks']"]


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

    from wdif.config.engine import HeuristicPolicy, TokenizerPolicy, WdifConfig

    config = WdifConfig(
        tokenizer=TokenizerPolicy(provider="regex", name="regex-default"),
        heuristics={
            "AGENT_LOOP": HeuristicPolicy(severity="WARNING", options={"repeated_call_threshold": 4})
        }
    )
    diagnostics = DiagnosticEngine(config=config).analyze([root])

    assert diagnostics[0].failure_type == FailureType.AGENT_LOOP
    assert diagnostics[0].severity == "WARNING"


def test_engine_uses_configured_extraction_mapping_for_drifted_prompt_schema():
    filler = "schema drift context " * 120
    fact = "SERVICE_TIER = platinum"
    span = TraceSpan(
        span_id="llm",
        parent_id=None,
        name="genai-call",
        span_type=SpanType.LLM,
        start_time_ms=0,
        end_time_ms=1,
        attributes={
            "gen_ai.prompt_text": f"{filler}{fact}{filler}",
            "custom_retriever.chunks": [{"id": "doc_custom", "content": fact}],
        },
    )

    from wdif.config.engine import ExtractionMappings, HeuristicPolicy, WdifConfig

    config = WdifConfig(
        extraction_mappings=ExtractionMappings(
            prompt=["$.attributes['gen_ai.prompt_text']"],
            documents=["$.attributes['custom_retriever.chunks']"],
        ),
        heuristics={
            "LOST_IN_THE_MIDDLE": HeuristicPolicy(options={"min_prompt_tokens": 50}),
            "CONTEXT_STUFFING": HeuristicPolicy(enabled=False),
            "RETRIEVER_MISS": HeuristicPolicy(enabled=False),
            "TOOL_ERROR": HeuristicPolicy(enabled=False),
            "AGENT_LOOP": HeuristicPolicy(enabled=False),
            "UNGROUNDED_ANSWER": HeuristicPolicy(enabled=False),
            "ORPHANED_SPAN_TREE": HeuristicPolicy(enabled=False),
        },
    )

    diagnostics = DiagnosticEngine(config=config).analyze([span])

    assert diagnostics[0].failure_type == FailureType.LOST_IN_THE_MIDDLE


def test_engine_routes_tokenizer_per_model_metadata():
    filler = "schema drift context " * 120
    fact = "SERVICE_TIER = platinum"
    span = TraceSpan(
        span_id="llm",
        parent_id=None,
        name="llama-call",
        span_type=SpanType.LLM,
        start_time_ms=0,
        end_time_ms=1,
        input_data={"prompts": [f"{filler}{fact}{filler}"]},
        attributes={
            "llm.model_name": "local-llama-3-70b",
            "openinference.retrieval.documents": [{"id": "doc_custom", "content": fact}],
        },
    )

    from wdif.config.engine import HeuristicPolicy, TokenizerRoute, WdifConfig

    config = WdifConfig(
        tokenizer_routes=[TokenizerRoute(match="llama", provider="regex", name="llama-regex")],
        heuristics={
            "LOST_IN_THE_MIDDLE": HeuristicPolicy(options={"min_prompt_tokens": 50}),
            "CONTEXT_STUFFING": HeuristicPolicy(enabled=False),
            "RETRIEVER_MISS": HeuristicPolicy(enabled=False),
            "TOOL_ERROR": HeuristicPolicy(enabled=False),
            "AGENT_LOOP": HeuristicPolicy(enabled=False),
            "UNGROUNDED_ANSWER": HeuristicPolicy(enabled=False),
            "ORPHANED_SPAN_TREE": HeuristicPolicy(enabled=False),
        },
    )

    diagnostics = DiagnosticEngine(config=config).analyze([span])

    assert diagnostics[0].metadata["tokenizer_provider"] == "regex"
    assert diagnostics[0].metadata["tokenizer_route"] == "llama"
    assert diagnostics[0].metadata["tokenizer_fidelity"] == "configured"


def test_unknown_model_tokenizer_fallback_is_explicit():
    span = TraceSpan(
        span_id="llm",
        parent_id=None,
        name="unknown-call",
        span_type=SpanType.LLM,
        start_time_ms=0,
        end_time_ms=1,
        attributes={"llm.model_name": "unknown-frontier-model"},
        input_data={"value": "token " * 100},
    )

    from wdif.config.engine import HeuristicPolicy, TokenizerPolicy, WdifConfig

    config = WdifConfig(
        tokenizer=TokenizerPolicy(provider="regex", name="regex-default"),
        heuristics={
            "CONTEXT_STUFFING": HeuristicPolicy(options={"max_context_tokens": 100}),
            "LOST_IN_THE_MIDDLE": HeuristicPolicy(enabled=False),
            "RETRIEVER_MISS": HeuristicPolicy(enabled=False),
            "TOOL_ERROR": HeuristicPolicy(enabled=False),
            "AGENT_LOOP": HeuristicPolicy(enabled=False),
            "UNGROUNDED_ANSWER": HeuristicPolicy(enabled=False),
            "ORPHANED_SPAN_TREE": HeuristicPolicy(enabled=False),
        },
    )

    diagnostics = DiagnosticEngine(config=config).analyze([span])

    assert diagnostics[0].metadata["tokenizer_fidelity"] == "fallback"
    assert "Unknown tokenizer family" in diagnostics[0].metadata["tokenizer_warning"]
    assert any("Unknown tokenizer family" in factor for factor in diagnostics[0].contributing_factors)
