from __future__ import annotations

from wdif.models import FailureDiagnostic, FailureType, SpanType, TraceSpan


class ToolErrorHeuristic:
    """Flags tool spans that explicitly failed or returned error-shaped output."""

    def analyze_span(self, span: TraceSpan) -> FailureDiagnostic | None:
        if span.span_type != SpanType.TOOL:
            return None

        status = str(span.attributes.get("status.code") or span.attributes.get("otel.status_code") or "")
        error_type = span.attributes.get("exception.type") or span.output_data.get("error_type")
        error_message = (
            span.attributes.get("exception.message")
            or span.output_data.get("error")
            or span.output_data.get("error_message")
        )

        if status.upper() not in {"ERROR", "STATUS_CODE_ERROR"} and not error_type and not error_message:
            return None

        return FailureDiagnostic(
            failure_type=FailureType.TOOL_ERROR,
            severity="CRITICAL",
            target_span_id=span.span_id,
            message=f"Tool span '{span.name}' failed before the agent could use its result.",
            metadata={
                "status": status or None,
                "error_type": error_type,
                "error_message": error_message,
            },
            suggested_fix=(
                "Handle the tool exception explicitly, return a typed failure payload, "
                "and prevent the agent from retrying identical inputs indefinitely."
            ),
        )
