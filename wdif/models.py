from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SpanType(Enum):
    LLM = "LLM"
    RETRIEVER = "RETRIEVER"
    CHAIN = "CHAIN"
    TOOL = "TOOL"
    AGENT = "AGENT"
    UNKNOWN = "UNKNOWN"


class FailureType(Enum):
    LOST_IN_THE_MIDDLE = "LOST_IN_THE_MIDDLE"
    CONTEXT_STUFFING = "CONTEXT_STUFFING"
    RETRIEVER_MISS = "RETRIEVER_MISS"
    AGENT_LOOP = "AGENT_LOOP"
    TOOL_ERROR = "TOOL_ERROR"
    UNGROUNDED_ANSWER = "UNGROUNDED_ANSWER"
    ORPHANED_SPAN_TREE = "ORPHANED_SPAN_TREE"


@dataclass
class TraceSpan:
    span_id: str
    parent_id: str | None
    name: str
    span_type: SpanType
    start_time_ms: int
    end_time_ms: int
    trace_id: str | None = None
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: dict[str, Any] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)
    children: list["TraceSpan"] = field(default_factory=list)

    @property
    def latency_ms(self) -> int:
        return max(0, self.end_time_ms - self.start_time_ms)

    def walk(self) -> list["TraceSpan"]:
        spans = [self]
        for child in self.children:
            spans.extend(child.walk())
        return spans


@dataclass
class FailureDiagnostic:
    failure_type: FailureType
    severity: str
    target_span_id: str
    message: str
    trace_id: str | None = None
    confidence_score: float = 0.0
    contributing_factors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    suggested_fix: str = ""

    def to_dict(self) -> dict[str, Any]:
        from wdif.security import sanitize_value

        return {
            "failure_type": self.failure_type.value,
            "severity": self.severity,
            "trace_id": self.trace_id,
            "target_span_id": self.target_span_id,
            "confidence_score": round(float(self.confidence_score), 3),
            "contributing_factors": sanitize_value(self.contributing_factors),
            "message": self.message,
            "metadata": sanitize_value(self.metadata),
            "suggested_fix": self.suggested_fix,
        }
