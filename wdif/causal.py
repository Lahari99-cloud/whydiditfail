from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace

from wdif.models import FailureDiagnostic, FailureType, TraceSpan


@dataclass(frozen=True)
class CausalEdge:
    source_index: int
    target_index: int
    reason: str


UPSTREAM_FAILURES = {
    FailureType.RETRIEVER_MISS,
    FailureType.TOOL_ERROR,
    FailureType.AGENT_LOOP,
    FailureType.ORPHANED_SPAN_TREE,
}

DOWNSTREAM_FAILURES = {
    FailureType.LOST_IN_THE_MIDDLE,
    FailureType.CONTEXT_STUFFING,
    FailureType.UNGROUNDED_ANSWER,
}


def annotate_causal_graph(
    roots: list[TraceSpan],
    diagnostics: list[FailureDiagnostic],
) -> list[FailureDiagnostic]:
    """Annotate diagnostics with deterministic propagation evidence from span topology."""

    if len(diagnostics) < 2:
        return diagnostics

    index = _SpanIndex(roots)
    edges = _build_edges(index, diagnostics)
    if not edges:
        return diagnostics

    incoming: dict[int, list[CausalEdge]] = defaultdict(list)
    outgoing: dict[int, list[CausalEdge]] = defaultdict(list)
    for edge in edges:
        incoming[edge.target_index].append(edge)
        outgoing[edge.source_index].append(edge)

    annotated = []
    for idx, diagnostic in enumerate(diagnostics):
        parents = incoming.get(idx, [])
        children = outgoing.get(idx, [])
        if parents:
            role = "downstream_effect"
        elif children:
            role = "primary_root_cause"
        else:
            role = "isolated"

        upstream_types = sorted(
            {diagnostics[edge.source_index].failure_type.value for edge in parents}
        )
        downstream_types = sorted(
            {diagnostics[edge.target_index].failure_type.value for edge in children}
        )
        chain = _causal_chain(idx, diagnostics, incoming)
        edge_reasons = [edge.reason for edge in parents] or [edge.reason for edge in children]

        metadata = {
            **diagnostic.metadata,
            "causal_role": role,
            "causal_upstream_failure_types": upstream_types,
            "causal_downstream_failure_types": downstream_types,
            "causal_chain": chain,
            "causal_edge_reasons": edge_reasons,
            "causal_propagation_depth": max(0, len(chain) - 1),
        }
        factors = list(diagnostic.contributing_factors)
        if parents:
            factors.append(
                "Causal propagation evidence: "
                + " -> ".join(
                    f"{diagnostics[edge.source_index].failure_type.value}@"
                    f"{diagnostics[edge.source_index].target_span_id}"
                    for edge in parents
                )
                + f" -> {diagnostic.failure_type.value}@{diagnostic.target_span_id}."
            )
        elif children:
            factors.append(
                "Likely upstream cause for: "
                + ", ".join(
                    f"{diagnostics[edge.target_index].failure_type.value}@"
                    f"{diagnostics[edge.target_index].target_span_id}"
                    for edge in children
                )
                + "."
            )

        annotated.append(
            replace(
                diagnostic,
                confidence_score=_adjust_confidence(diagnostic.confidence_score, role),
                contributing_factors=_dedupe(factors),
                metadata=metadata,
            )
        )
    return annotated


def _build_edges(index: "_SpanIndex", diagnostics: list[FailureDiagnostic]) -> list[CausalEdge]:
    edges = []
    for source_idx, source in enumerate(diagnostics):
        for target_idx, target in enumerate(diagnostics):
            if source_idx == target_idx:
                continue
            reason = _edge_reason(index, source, target)
            if reason:
                edges.append(CausalEdge(source_idx, target_idx, reason))
    return _dedupe_edges(edges)


def _edge_reason(
    index: "_SpanIndex",
    source: FailureDiagnostic,
    target: FailureDiagnostic,
) -> str | None:
    if (source.trace_id or "<unknown>") != (target.trace_id or "<unknown>"):
        return None
    if not index.can_precede(source.target_span_id, target.target_span_id):
        return None

    if source.failure_type in UPSTREAM_FAILURES and target.failure_type in DOWNSTREAM_FAILURES:
        return "upstream structural failure occurred before downstream LLM/context symptom"

    if (
        source.failure_type == FailureType.CONTEXT_STUFFING
        and target.failure_type in {FailureType.LOST_IN_THE_MIDDLE, FailureType.UNGROUNDED_ANSWER}
    ):
        return "prompt overload can amplify attention degradation or weak grounding"

    if (
        source.failure_type == FailureType.LOST_IN_THE_MIDDLE
        and target.failure_type == FailureType.UNGROUNDED_ANSWER
    ):
        return "answer-critical evidence was present but buried before weak grounding"

    return None


def _causal_chain(
    diagnostic_index: int,
    diagnostics: list[FailureDiagnostic],
    incoming: dict[int, list[CausalEdge]],
) -> list[str]:
    chain_indices = []
    current = diagnostic_index
    seen = set()
    while current not in seen:
        seen.add(current)
        chain_indices.append(current)
        parents = incoming.get(current, [])
        if not parents:
            break
        current = min(
            (edge.source_index for edge in parents),
            key=lambda idx: diagnostics[idx].confidence_score,
        )

    chain_indices.reverse()
    return [
        f"{diagnostics[idx].failure_type.value}@{diagnostics[idx].target_span_id}"
        for idx in chain_indices
    ]


def _adjust_confidence(score: float, role: str) -> float:
    if role == "primary_root_cause":
        return round(min(0.99, score + 0.04), 3)
    if role == "downstream_effect":
        return round(min(0.99, score + 0.02), 3)
    return score


def _dedupe_edges(edges: list[CausalEdge]) -> list[CausalEdge]:
    seen = set()
    deduped = []
    for edge in edges:
        key = (edge.source_index, edge.target_index, edge.reason)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(edge)
    return deduped


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


class _SpanIndex:
    def __init__(self, roots: list[TraceSpan]):
        self.starts: dict[str, int] = {}
        self.depths: dict[str, int] = {}
        self.ancestors: dict[str, set[str]] = {}
        for root in roots:
            self._index(root, depth=0, ancestors=set())

    def can_precede(self, source_span_id: str, target_span_id: str) -> bool:
        if source_span_id == target_span_id:
            return True
        if source_span_id in self.ancestors.get(target_span_id, set()):
            return True
        source_start = self.starts.get(source_span_id)
        target_start = self.starts.get(target_span_id)
        if source_start is None or target_start is None:
            return True
        return source_start <= target_start

    def _index(self, span: TraceSpan, depth: int, ancestors: set[str]) -> None:
        self.starts[span.span_id] = span.start_time_ms
        self.depths[span.span_id] = depth
        self.ancestors[span.span_id] = set(ancestors)
        for child in span.children:
            self._index(child, depth + 1, {*ancestors, span.span_id})
