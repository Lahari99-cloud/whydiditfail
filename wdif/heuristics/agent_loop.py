from __future__ import annotations

from collections import Counter

from wdif.models import FailureDiagnostic, FailureType, SpanType, TraceSpan


class AgentLoopHeuristic:
    """Detects repeated tool/agent calls that indicate an execution loop."""

    def __init__(self, repeated_call_threshold: int = 4):
        self.repeated_call_threshold = repeated_call_threshold

    def analyze_tree(self, root: TraceSpan) -> list[FailureDiagnostic]:
        spans = [
            span
            for span in root.walk()
            if span.span_type in {SpanType.TOOL, SpanType.AGENT, SpanType.CHAIN}
        ]
        signatures = Counter(self._signature(span) for span in spans)
        diagnostics: list[FailureDiagnostic] = []

        for signature, count in signatures.items():
            if count < self.repeated_call_threshold:
                continue
            target = next(span for span in spans if self._signature(span) == signature)
            diagnostics.append(
                FailureDiagnostic(
                    failure_type=FailureType.AGENT_LOOP,
                    severity="CRITICAL",
                    target_span_id=target.span_id,
                    message=f"Repeated agent/tool call pattern detected {count} times: {signature}.",
                    metadata={"signature": signature, "repeat_count": count},
                    suggested_fix=(
                        "Add max-iteration guards, persist tool results in state, and stop retrying "
                        "when tool inputs are unchanged."
                    ),
                )
            )

        return diagnostics

    @staticmethod
    def _signature(span: TraceSpan) -> str:
        normalized_input = str(span.input_data)[:500]
        return f"{span.span_type.value}:{span.name}:{normalized_input}"
