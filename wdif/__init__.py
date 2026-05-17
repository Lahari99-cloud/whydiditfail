"""WhyDidItFail: deterministic local diagnostics for AI trace failures."""

from wdif.engine import DiagnosticEngine
from wdif.models import FailureDiagnostic, FailureType, SpanType, TraceSpan
from wdif.parser import OpenInferenceParser

__all__ = [
    "DiagnosticEngine",
    "FailureDiagnostic",
    "FailureType",
    "OpenInferenceParser",
    "SpanType",
    "TraceSpan",
]
