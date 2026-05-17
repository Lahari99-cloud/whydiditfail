from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import replace

from wdif.models import FailureDiagnostic, FailureType


SEVERITY_RANK = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}


def rank_diagnostics(diagnostics: list[FailureDiagnostic]) -> list[FailureDiagnostic]:
    """Attach RCA confidence/evidence metadata and return findings in priority order."""

    enriched = [_with_confidence(diagnostic) for diagnostic in diagnostics]
    enriched = _with_multicausal_context(enriched)
    return sorted(
        enriched,
        key=lambda item: (
            SEVERITY_RANK.get(item.severity, 9),
            -item.confidence_score,
            item.failure_type.value,
        ),
    )


def _with_confidence(diagnostic: FailureDiagnostic) -> FailureDiagnostic:
    if diagnostic.confidence_score > 0:
        return diagnostic

    score, factors = _score(diagnostic)
    return replace(
        diagnostic,
        confidence_score=round(_clamp(score), 3),
        contributing_factors=_dedupe([*diagnostic.contributing_factors, *factors]),
    )


def _score(diagnostic: FailureDiagnostic) -> tuple[float, list[str]]:
    metadata = diagnostic.metadata
    factors = [f"Matched deterministic rule {diagnostic.failure_type.value}."]

    if diagnostic.failure_type == FailureType.LOST_IN_THE_MIDDLE:
        position = _float(metadata.get("chunk_position_percentage"), default=50.0)
        distance_from_center = abs(position - 50.0)
        score = 0.9 - min(distance_from_center / 100.0, 0.25)
        factors.append(f"Evidence chunk is at {position:.1f}% of prompt depth.")
        if metadata.get("tokenizer_fidelity") == "fallback":
            score -= 0.1
            warning = metadata.get("tokenizer_warning") or "Tokenizer route fell back to global/default geometry."
            factors.append(str(warning))
        if metadata.get("token_count_mode") == "estimated":
            score -= 0.08
            factors.append("Token position was estimated from a bounded context-bomb sample.")
        return score, factors

    if diagnostic.failure_type == FailureType.CONTEXT_STUFFING:
        ratio = _float(metadata.get("usage_ratio"), default=1.0)
        score = 0.68 + min(ratio / 10.0, 0.27)
        factors.append(f"Prompt uses {ratio:.2f}x configured context budget.")
        if metadata.get("tokenizer_fidelity") == "fallback":
            score -= 0.08
            warning = metadata.get("tokenizer_warning") or "Tokenizer route fell back to global/default geometry."
            factors.append(str(warning))
        if metadata.get("token_count_mode") == "estimated":
            score -= 0.05
            factors.append("Token count used bounded estimation to avoid OOM risk.")
        return score, factors

    if diagnostic.failure_type == FailureType.RETRIEVER_MISS:
        doc_count = _float(metadata.get("document_count"), default=0.0)
        if doc_count == 0:
            factors.append("Retriever returned zero usable documents.")
            return 0.92, factors
        max_score = _float(metadata.get("max_score"), default=0.0)
        factors.append(f"Best retriever score is {max_score:.3f}.")
        return 0.72, factors

    if diagnostic.failure_type == FailureType.AGENT_LOOP:
        repeat_count = _float(metadata.get("repeat_count"), default=2.0)
        factors.append(f"Repeated identical action signature {int(repeat_count)} time(s).")
        return 0.78 + min(repeat_count / 50.0, 0.17), factors

    if diagnostic.failure_type == FailureType.TOOL_ERROR:
        factors.append("Tool output matched configured error indicators.")
        return 0.82, factors

    if diagnostic.failure_type == FailureType.UNGROUNDED_ANSWER:
        support_ratio = _float(metadata.get("support_ratio"), default=0.0)
        if "support_ratio" in metadata:
            factors.append(f"Answer/support term overlap is {support_ratio:.3f}.")
            return 0.74 + min((0.25 - support_ratio), 0.16), factors
        factors.append("Substantial answer was emitted without attached retrieval evidence.")
        return 0.78, factors

    if diagnostic.failure_type == FailureType.ORPHANED_SPAN_TREE:
        factors.append("Span references a parent that was not resolved in the trace payload.")
        return 0.7, factors

    return 0.55, factors


def _with_multicausal_context(diagnostics: list[FailureDiagnostic]) -> list[FailureDiagnostic]:
    by_trace: dict[str, list[FailureDiagnostic]] = defaultdict(list)
    by_span: dict[tuple[str, str], list[FailureDiagnostic]] = defaultdict(list)
    for diagnostic in diagnostics:
        trace_key = diagnostic.trace_id or "<unknown>"
        by_trace[trace_key].append(diagnostic)
        by_span[(trace_key, diagnostic.target_span_id)].append(diagnostic)

    enriched = []
    for diagnostic in diagnostics:
        trace_key = diagnostic.trace_id or "<unknown>"
        factors = list(diagnostic.contributing_factors)
        score = diagnostic.confidence_score

        same_trace_types = sorted(
            {
                item.failure_type.value
                for item in by_trace[trace_key]
                if item.failure_type != diagnostic.failure_type
            }
        )
        same_span_types = sorted(
            {
                item.failure_type.value
                for item in by_span[(trace_key, diagnostic.target_span_id)]
                if item.failure_type != diagnostic.failure_type
            }
        )

        if same_span_types:
            score += 0.04
            factors.append(f"Same span also triggered: {', '.join(same_span_types)}.")
        elif same_trace_types:
            score += 0.02
            factors.append(f"Same trace also triggered: {', '.join(same_trace_types)}.")

        trace_counts = Counter(item.failure_type.value for item in by_trace[trace_key])
        if sum(trace_counts.values()) > 1:
            metadata = {
                **diagnostic.metadata,
                "co_occurring_failure_types": dict(sorted(trace_counts.items())),
            }
        else:
            metadata = diagnostic.metadata

        enriched.append(
            replace(
                diagnostic,
                confidence_score=round(_clamp(score), 3),
                contributing_factors=_dedupe(factors),
                metadata=metadata,
            )
        )
    return enriched


def _float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float) -> float:
    return max(0.0, min(0.99, value))


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
