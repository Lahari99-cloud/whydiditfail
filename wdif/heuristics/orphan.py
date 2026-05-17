from __future__ import annotations

from wdif.models import FailureDiagnostic, FailureType, TraceSpan


class OrphanedSpanHeuristic:
    """Flags spans whose declared parent was not present after staging."""

    def analyze_tree(self, root: TraceSpan) -> list[FailureDiagnostic]:
        diagnostics: list[FailureDiagnostic] = []
        for span in root.walk():
            missing_parent = span.attributes.get("wdif.orphaned_parent_id")
            if not missing_parent:
                continue
            diagnostics.append(
                FailureDiagnostic(
                    failure_type=FailureType.ORPHANED_SPAN_TREE,
                    severity="WARNING",
                    trace_id=span.trace_id,
                    target_span_id=span.span_id,
                    message=(
                        f"Span '{span.span_id}' references missing parent '{missing_parent}'."
                    ),
                    metadata={
                        "missing_parent_id": missing_parent,
                        "span_id": span.span_id,
                        "trace_id": span.trace_id,
                    },
                    suggested_fix=(
                        "Increase the staging window or inspect upstream collector delivery for "
                        "dropped parent spans."
                    ),
                )
            )
        return diagnostics
