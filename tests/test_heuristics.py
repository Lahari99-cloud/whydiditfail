from wdif.engine import DiagnosticEngine
from wdif.heuristics.agent_loop import AgentLoopHeuristic
from wdif.heuristics.attention import LostInTheMiddleHeuristic
from wdif.heuristics.context import ContextStuffingHeuristic
from wdif.heuristics.retriever import RetrieverMissHeuristic
from wdif.heuristics.grounding import UngroundedAnswerHeuristic
from wdif.heuristics.tool_error import ToolErrorHeuristic
from wdif.models import FailureType, SpanType, TraceSpan


def test_lost_in_the_middle_detects_buried_retrieved_chunk():
    filler = "alpha " * 100
    fact = "TARGET_VARIABLE_VALUE MATCH_SUCCESSFUL"
    prompt = f"{filler}{fact}{filler}"
    span = TraceSpan(
        span_id="llm",
        parent_id=None,
        name="answer",
        span_type=SpanType.LLM,
        start_time_ms=0,
        end_time_ms=1,
        input_data={"prompts": [prompt]},
        attributes={"openinference.retrieval.documents": [{"id": "doc_1", "content": fact}]},
    )

    diagnostic = LostInTheMiddleHeuristic(min_prompt_tokens=50).analyze_span(span)

    assert diagnostic is not None
    assert diagnostic.failure_type == FailureType.LOST_IN_THE_MIDDLE
    assert diagnostic.metadata["chunk_id"] == "doc_1"


def test_context_stuffing_detects_near_budget_prompt():
    span = TraceSpan(
        span_id="llm",
        parent_id=None,
        name="answer",
        span_type=SpanType.LLM,
        start_time_ms=0,
        end_time_ms=1,
        input_data={"value": "token " * 100},
    )

    diagnostic = ContextStuffingHeuristic(max_context_tokens=100, warning_ratio=0.8).analyze_span(span)

    assert diagnostic is not None
    assert diagnostic.failure_type == FailureType.CONTEXT_STUFFING


def test_retriever_miss_detects_empty_results():
    span = TraceSpan(
        span_id="retriever",
        parent_id=None,
        name="search",
        span_type=SpanType.RETRIEVER,
        start_time_ms=0,
        end_time_ms=1,
        output_data={"documents": []},
    )

    diagnostic = RetrieverMissHeuristic().analyze_span(span)

    assert diagnostic is not None
    assert diagnostic.failure_type == FailureType.RETRIEVER_MISS


def test_agent_loop_detects_repeated_tool_calls():
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
            name="search",
            span_type=SpanType.TOOL,
            start_time_ms=idx,
            end_time_ms=idx + 1,
            input_data={"query": "same"},
        )
        for idx in range(4)
    ]

    diagnostics = AgentLoopHeuristic(repeated_call_threshold=4).analyze_tree(root)

    assert len(diagnostics) == 1
    assert diagnostics[0].failure_type == FailureType.AGENT_LOOP


def test_engine_runs_multiple_heuristics():
    retriever = TraceSpan(
        span_id="retriever",
        parent_id=None,
        name="search",
        span_type=SpanType.RETRIEVER,
        start_time_ms=0,
        end_time_ms=1,
        output_data={"documents": []},
    )

    diagnostics = DiagnosticEngine(tree_heuristics=[]).analyze([retriever])

    assert [item.failure_type for item in diagnostics] == [FailureType.RETRIEVER_MISS]


def test_tool_error_detects_failed_tool_span():
    span = TraceSpan(
        span_id="tool",
        parent_id=None,
        name="lookup",
        span_type=SpanType.TOOL,
        start_time_ms=0,
        end_time_ms=1,
        attributes={"status.code": "ERROR", "exception.message": "timeout"},
    )

    diagnostic = ToolErrorHeuristic().analyze_span(span)

    assert diagnostic is not None
    assert diagnostic.failure_type == FailureType.TOOL_ERROR


def test_ungrounded_answer_detects_missing_evidence():
    span = TraceSpan(
        span_id="llm",
        parent_id=None,
        name="answer",
        span_type=SpanType.LLM,
        start_time_ms=0,
        end_time_ms=1,
        output_data={
            "value": (
                "PremiumEnterpriseRefunds are available after 90 days through "
                "the PlatinumSuccessGuarantee for ContosoEnterpriseAccounts."
            )
        },
    )

    diagnostic = UngroundedAnswerHeuristic(min_answer_chars=40).analyze_span(span)

    assert diagnostic is not None
    assert diagnostic.failure_type == FailureType.UNGROUNDED_ANSWER


def test_engine_annotates_causal_failure_propagation():
    root = TraceSpan(
        span_id="root",
        parent_id=None,
        name="chain",
        span_type=SpanType.CHAIN,
        start_time_ms=0,
        end_time_ms=100,
        trace_id="trace-causal",
    )
    retriever = TraceSpan(
        span_id="retriever",
        parent_id="root",
        name="search",
        span_type=SpanType.RETRIEVER,
        start_time_ms=10,
        end_time_ms=20,
        trace_id="trace-causal",
        output_data={"documents": []},
    )
    llm = TraceSpan(
        span_id="llm",
        parent_id="root",
        name="answer",
        span_type=SpanType.LLM,
        start_time_ms=30,
        end_time_ms=60,
        trace_id="trace-causal",
        output_data={
            "value": (
                "PremiumEnterpriseRefunds are available after 90 days through "
                "the PlatinumSuccessGuarantee for ContosoEnterpriseAccounts."
            )
        },
    )
    root.children = [retriever, llm]

    diagnostics = DiagnosticEngine().analyze([root])
    retriever_diag = next(item for item in diagnostics if item.failure_type == FailureType.RETRIEVER_MISS)
    answer_diag = next(item for item in diagnostics if item.failure_type == FailureType.UNGROUNDED_ANSWER)

    assert retriever_diag.metadata["causal_role"] == "primary_root_cause"
    assert "UNGROUNDED_ANSWER" in retriever_diag.metadata["causal_downstream_failure_types"]
    assert answer_diag.metadata["causal_role"] == "downstream_effect"
    assert answer_diag.metadata["causal_chain"] == [
        "RETRIEVER_MISS@retriever",
        "UNGROUNDED_ANSWER@llm",
    ]
    assert any("Causal propagation evidence" in item for item in answer_diag.contributing_factors)
