from __future__ import annotations

from wdif.extractors import extract_documents
from wdif.models import FailureDiagnostic, FailureType, SpanType, TraceSpan


class RetrieverMissHeuristic:
    """Flags retriever spans that return too few or low-scoring documents."""

    def __init__(self, min_documents: int = 1, min_score: float = 0.3):
        self.min_documents = min_documents
        self.min_score = min_score

    def analyze_span(self, span: TraceSpan) -> FailureDiagnostic | None:
        if span.span_type != SpanType.RETRIEVER:
            return None

        documents = extract_documents(span)
        if len(documents) < self.min_documents:
            return FailureDiagnostic(
                failure_type=FailureType.RETRIEVER_MISS,
                severity="CRITICAL",
                target_span_id=span.span_id,
                message=f"Retriever returned {len(documents)} documents.",
                metadata={"document_count": len(documents)},
                suggested_fix="Check query rewriting, embedding index freshness, filters, and top_k settings.",
            )

        scored_documents = [doc for doc in documents if isinstance(doc.get("score"), (int, float))]
        if scored_documents and max(float(doc["score"]) for doc in scored_documents) < self.min_score:
            return FailureDiagnostic(
                failure_type=FailureType.RETRIEVER_MISS,
                severity="WARNING",
                target_span_id=span.span_id,
                message="Retriever returned documents, but all scores are below the confidence threshold.",
                metadata={
                    "document_count": len(documents),
                    "max_score": max(float(doc["score"]) for doc in scored_documents),
                    "min_score": self.min_score,
                },
                suggested_fix="Tune retrieval query generation, embedding model alignment, or ranking thresholds.",
            )

        return None
