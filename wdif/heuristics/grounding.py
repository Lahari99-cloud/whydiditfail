from __future__ import annotations

import re

from wdif.extractors import SpanExtractor, extract_documents, extract_output_text
from wdif.models import FailureDiagnostic, FailureType, SpanType, TraceSpan


class UngroundedAnswerHeuristic:
    """Flags answers that contain citations or factual claims without retrieved support."""

    def __init__(self, min_answer_chars: int = 80, extractor: SpanExtractor | None = None):
        self.min_answer_chars = min_answer_chars
        self.extractor = extractor

    def analyze_span(self, span: TraceSpan) -> FailureDiagnostic | None:
        if span.span_type != SpanType.LLM:
            return None

        answer = extract_output_text(span, self.extractor)
        if len(answer) < self.min_answer_chars:
            return None

        return self._analyze_with_documents(span, answer, extract_documents(span, self.extractor))

    def analyze_tree(self, root: TraceSpan) -> list[FailureDiagnostic]:
        tree_documents = []
        for span in root.walk():
            tree_documents.extend(extract_documents(span, self.extractor))

        diagnostics: list[FailureDiagnostic] = []
        for span in root.walk():
            if span.span_type != SpanType.LLM:
                continue
            answer = extract_output_text(span, self.extractor)
            if len(answer) < self.min_answer_chars:
                continue
            documents = extract_documents(span, self.extractor) or tree_documents
            diagnostic = self._analyze_with_documents(span, answer, documents)
            if diagnostic:
                diagnostics.append(diagnostic)
        return diagnostics

    def _analyze_with_documents(
        self,
        span: TraceSpan,
        answer: str,
        documents: list[dict],
    ) -> FailureDiagnostic | None:
        if not documents:
            return FailureDiagnostic(
                failure_type=FailureType.UNGROUNDED_ANSWER,
                severity="WARNING",
                target_span_id=span.span_id,
                message="LLM produced a substantial answer without retriever evidence attached to the span.",
                metadata={"answer_chars": len(answer)},
                suggested_fix=(
                    "Attach retrieved documents to the LLM span or require citation-grounded generation."
                ),
            )

        doc_text = " ".join(str(doc.get("content") or doc.get("text") or "") for doc in documents)
        answer_terms = _important_terms(answer)
        if not answer_terms:
            return None

        supported = sum(1 for term in answer_terms if term.lower() in doc_text.lower())
        support_ratio = supported / len(answer_terms)
        if support_ratio >= 0.25:
            return None

        return FailureDiagnostic(
            failure_type=FailureType.UNGROUNDED_ANSWER,
            severity="WARNING",
            target_span_id=span.span_id,
            message="Answer terms have weak overlap with retrieved context.",
            metadata={
                "answer_terms_checked": len(answer_terms),
                "supported_terms": supported,
                "support_ratio": round(support_ratio, 3),
            },
            suggested_fix="Re-rank retrieved context, require citations, or fail closed when grounding is weak.",
        )


def _important_terms(text: str) -> set[str]:
    terms = set(re.findall(r"\b[A-Z][A-Za-z0-9_]{3,}\b|\b[A-Za-z0-9_]{10,}\b", text))
    stop = {"According", "Therefore", "However", "Because", "Retrieved", "Context"}
    return {term for term in terms if term not in stop}
