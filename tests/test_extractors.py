from wdif.extractors import extract_documents, extract_output_text, extract_prompt
from wdif.models import SpanType, TraceSpan


def test_extract_prompt_from_openinference_input_value_json_messages():
    span = TraceSpan(
        span_id="llm",
        parent_id=None,
        name="answer",
        span_type=SpanType.LLM,
        start_time_ms=0,
        end_time_ms=1,
        input_data={"value": '[{"role": "user", "content": "What is the refund policy?"}]'},
    )

    assert extract_prompt(span) == "What is the refund policy?"


def test_extract_documents_from_numbered_attributes():
    span = TraceSpan(
        span_id="retriever",
        parent_id=None,
        name="search",
        span_type=SpanType.RETRIEVER,
        start_time_ms=0,
        end_time_ms=1,
        attributes={
            "retrieval.documents.0.content": "Refunds are available within 30 days.",
            "retrieval.documents.0.score": 0.72,
        },
    )

    assert extract_documents(span) == [
        {"content": "Refunds are available within 30 days.", "score": 0.72}
    ]


def test_extract_output_text_from_attributes():
    span = TraceSpan(
        span_id="llm",
        parent_id=None,
        name="answer",
        span_type=SpanType.LLM,
        start_time_ms=0,
        end_time_ms=1,
        attributes={"output.value": "Final answer"},
    )

    assert extract_output_text(span) == "Final answer"
