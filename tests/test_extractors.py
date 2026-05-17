from wdif.config.engine import ExtractionMappings
from wdif.extractors import SpanExtractor, extract_documents, extract_output_text, extract_prompt
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


def test_configured_extractor_reads_drifted_genai_attributes():
    span = TraceSpan(
        span_id="llm",
        parent_id=None,
        name="answer",
        span_type=SpanType.LLM,
        start_time_ms=0,
        end_time_ms=1,
        attributes={
            "gen_ai.prompt_text": "System context\nUser: verify policy",
            "custom_retriever.chunks": [
                {"id": "doc_custom", "content": "POLICY_ID = SEC-19", "score": 0.91}
            ],
            "gen_ai.response.text": "Policy SEC-19 applies.",
        },
    )
    extractor = SpanExtractor(
        ExtractionMappings(
            prompt=["$.attributes['gen_ai.prompt_text']"],
            documents=["$.attributes['custom_retriever.chunks']"],
            output_text=["$.attributes['gen_ai.response.text']"],
        )
    )

    assert extract_prompt(span, extractor) == "System context\nUser: verify policy"
    assert extract_documents(span, extractor)[0]["id"] == "doc_custom"
    assert extract_output_text(span, extractor) == "Policy SEC-19 applies."
