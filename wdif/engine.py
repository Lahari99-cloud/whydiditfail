from __future__ import annotations

from dataclasses import replace

from wdif.config import WdifConfig
from wdif.extractors import SpanExtractor
from wdif.heuristics import (
    AgentLoopHeuristic,
    ContextStuffingHeuristic,
    LostInTheMiddleHeuristic,
    OrphanedSpanHeuristic,
    RetrieverMissHeuristic,
    ToolErrorHeuristic,
    UngroundedAnswerHeuristic,
)
from wdif.models import FailureDiagnostic, FailureType, TraceSpan
from wdif.tokenization import TokenCounter


class DiagnosticEngine:
    """Runs deterministic diagnostics over parsed trace trees."""

    def __init__(
        self,
        span_heuristics: list[object] | None = None,
        tree_heuristics: list[object] | None = None,
        config: WdifConfig | None = None,
    ):
        self.config = config or WdifConfig.default()
        token_counter = TokenCounter.from_policy(self.config.tokenizer)
        extractor = SpanExtractor(self.config.extraction_mappings)
        default_span_heuristics, default_tree_heuristics = self._build_heuristics(
            token_counter,
            extractor,
        )
        self.span_heuristics = default_span_heuristics if span_heuristics is None else span_heuristics
        self.tree_heuristics = default_tree_heuristics if tree_heuristics is None else tree_heuristics

    def analyze(self, roots: list[TraceSpan]) -> list[FailureDiagnostic]:
        diagnostics: list[FailureDiagnostic] = []

        for root in roots:
            for heuristic in self.tree_heuristics:
                analyze_tree = getattr(heuristic, "analyze_tree", None)
                if analyze_tree:
                    diagnostics.extend(
                        self._apply_policy(
                            diagnostic if diagnostic.trace_id else replace(diagnostic, trace_id=root.trace_id)
                        )
                        for diagnostic in analyze_tree(root)
                    )

            for span in root.walk():
                for heuristic in self.span_heuristics:
                    analyze_span = getattr(heuristic, "analyze_span", None)
                    if not analyze_span:
                        continue
                    diagnostic = analyze_span(span)
                    if diagnostic:
                        diagnostics.append(
                            self._apply_policy(self._with_span_identity(diagnostic, span))
                        )

        return sorted(
            diagnostics,
            key=lambda item: (self._severity_rank(item.severity), item.failure_type.value),
        )

    def _build_heuristics(
        self,
        token_counter: TokenCounter,
        extractor: SpanExtractor,
    ) -> tuple[list[object], list[object]]:
        span_heuristics: list[object] = []
        tree_heuristics: list[object] = []

        if self._enabled(FailureType.LOST_IN_THE_MIDDLE):
            policy = self.config.policy_for(FailureType.LOST_IN_THE_MIDDLE.value)
            span_heuristics.append(
                LostInTheMiddleHeuristic(
                    token_counter=token_counter,
                    min_prompt_tokens=int(policy.options.get("min_prompt_tokens", 4000)),
                    blindspot_start_pct=float(policy.options.get("blindspot_start_pct", 20.0)),
                    blindspot_end_pct=float(policy.options.get("blindspot_end_pct", 80.0)),
                    max_prompt_chars=int(policy.options.get("max_prompt_chars", 100_000)),
                    extractor=extractor,
                )
            )

        if self._enabled(FailureType.CONTEXT_STUFFING):
            policy = self.config.policy_for(FailureType.CONTEXT_STUFFING.value)
            span_heuristics.append(
                ContextStuffingHeuristic(
                    token_counter=token_counter,
                    max_context_tokens=int(policy.options.get("max_context_tokens", 8192)),
                    warning_ratio=float(policy.options.get("warning_ratio", 0.9)),
                    max_prompt_chars=int(policy.options.get("max_prompt_chars", 100_000)),
                    extractor=extractor,
                )
            )

        if self._enabled(FailureType.RETRIEVER_MISS):
            policy = self.config.policy_for(FailureType.RETRIEVER_MISS.value)
            span_heuristics.append(
                RetrieverMissHeuristic(
                    min_documents=int(policy.options.get("min_documents", 1)),
                    min_score=float(policy.options.get("min_score", 0.3)),
                    extractor=extractor,
                )
            )

        if self._enabled(FailureType.TOOL_ERROR):
            span_heuristics.append(ToolErrorHeuristic())

        if self._enabled(FailureType.AGENT_LOOP):
            policy = self.config.policy_for(FailureType.AGENT_LOOP.value)
            tree_heuristics.append(
                AgentLoopHeuristic(
                    repeated_call_threshold=int(policy.options.get("repeated_call_threshold", 4))
                )
            )

        if self._enabled(FailureType.UNGROUNDED_ANSWER):
            policy = self.config.policy_for(FailureType.UNGROUNDED_ANSWER.value)
            tree_heuristics.append(
                UngroundedAnswerHeuristic(
                    min_answer_chars=int(policy.options.get("min_answer_chars", 80)),
                    extractor=extractor,
                )
            )

        if self._enabled(FailureType.ORPHANED_SPAN_TREE):
            tree_heuristics.append(OrphanedSpanHeuristic())

        return span_heuristics, tree_heuristics

    def _enabled(self, failure_type: FailureType) -> bool:
        return self.config.policy_for(failure_type.value).enabled

    def _apply_policy(self, diagnostic: FailureDiagnostic) -> FailureDiagnostic:
        policy = self.config.policy_for(diagnostic.failure_type.value)
        if not policy.severity:
            return diagnostic
        return replace(diagnostic, severity=policy.severity)

    @staticmethod
    def _with_span_identity(diagnostic: FailureDiagnostic, span: TraceSpan) -> FailureDiagnostic:
        if diagnostic.trace_id:
            return diagnostic
        return replace(diagnostic, trace_id=span.trace_id)

    @staticmethod
    def _severity_rank(severity: str) -> int:
        return {"CRITICAL": 0, "WARNING": 1, "INFO": 2}.get(severity, 9)
