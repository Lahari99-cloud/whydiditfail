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

    def to_snapshot(self) -> dict[str, Any]:
        """Serialize a span tree deterministically for replay snapshots."""
        return {
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "span_type": self.span_type.value,
            "start_time_ms": self.start_time_ms,
            "end_time_ms": self.end_time_ms,
            "trace_id": self.trace_id,
            "input_data": self.input_data,
            "output_data": self.output_data,
            "attributes": self.attributes,
            "children": [child.to_snapshot() for child in self.children],
        }

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> "TraceSpan":
        """Deserialize a replay snapshot span without lossy conversion."""
        span = cls(
            span_id=str(data["span_id"]),
            parent_id=data.get("parent_id"),
            name=str(data.get("name", "unnamed_span")),
            span_type=SpanType(str(data.get("span_type", SpanType.UNKNOWN.value))),
            start_time_ms=int(data.get("start_time_ms", 0)),
            end_time_ms=int(data.get("end_time_ms", 0)),
            trace_id=data.get("trace_id"),
            input_data=dict(data.get("input_data", {})),
            output_data=dict(data.get("output_data", {})),
            attributes=dict(data.get("attributes", {})),
        )
        span.children = [cls.from_snapshot(child) for child in data.get("children", [])]
        return span


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
