from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass
class DeadLetterRecord:
    source: str
    line_number: int
    error: str
    raw_excerpt: str


@dataclass
class StreamReadResult:
    payloads: list[dict[str, Any]] = field(default_factory=list)
    dead_letters: list[DeadLetterRecord] = field(default_factory=list)


class DeadLetterQueue:
    def __init__(self, path: Path | None = None):
        self.path = path
        self.records: list[DeadLetterRecord] = []

    def append(self, record: DeadLetterRecord) -> None:
        self.records.append(record)
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.__dict__) + "\n")


class TraceStagingBuffer:
    """Groups spans by trace_id across files before graph construction."""

    def __init__(self, max_traces: int = 10_000):
        self.max_traces = max_traces
        self._groups: dict[str, list[dict[str, Any]]] = {}
        self._payloads: list[dict[str, Any]] = []

    def add(self, payload: dict[str, Any]) -> None:
        if is_single_span(payload):
            trace_id = str(payload.get("trace_id") or payload.get("traceId") or "__default__")
            self._groups.setdefault(trace_id, []).append(payload)
            self._evict_if_needed()
        else:
            self._payloads.append(payload)

    def extend(self, payloads: Iterable[dict[str, Any]]) -> None:
        for payload in payloads:
            self.add(payload)

    def flush(self) -> list[dict[str, Any]]:
        staged = list(self._payloads)
        staged.extend({"spans": spans} for spans in self._groups.values())
        self._groups.clear()
        self._payloads.clear()
        return staged

    def _evict_if_needed(self) -> None:
        while len(self._groups) > self.max_traces:
            oldest_key = next(iter(self._groups))
            self._payloads.append({"spans": self._groups.pop(oldest_key)})


def read_json_stream(
    trace_file: Path,
    dlq: DeadLetterQueue | None = None,
) -> StreamReadResult:
    result = StreamReadResult()
    suffix = trace_file.suffix.lower()

    if suffix == ".jsonl":
        with trace_file.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    record = DeadLetterRecord(
                        source=str(trace_file),
                        line_number=line_number,
                        error=str(exc),
                        raw_excerpt=line[:500],
                    )
                    result.dead_letters.append(record)
                    if dlq:
                        dlq.append(record)
                    continue
                if isinstance(payload, dict):
                    result.payloads.append(payload)
                else:
                    record = DeadLetterRecord(
                        source=str(trace_file),
                        line_number=line_number,
                        error=f"Expected JSON object, received {type(payload).__name__}",
                        raw_excerpt=line[:500],
                    )
                    result.dead_letters.append(record)
                    if dlq:
                        dlq.append(record)
        return result

    try:
        with trace_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        record = DeadLetterRecord(
            source=str(trace_file),
            line_number=1,
            error=str(exc),
            raw_excerpt=trace_file.read_text(encoding="utf-8", errors="replace")[:500],
        )
        result.dead_letters.append(record)
        if dlq:
            dlq.append(record)
        return result

    if isinstance(payload, list):
        result.payloads.extend(item for item in payload if isinstance(item, dict))
    elif isinstance(payload, dict):
        result.payloads.append(payload)
    else:
        record = DeadLetterRecord(
            source=str(trace_file),
            line_number=1,
            error=f"Expected JSON object or array, received {type(payload).__name__}",
            raw_excerpt=str(payload)[:500],
        )
        result.dead_letters.append(record)
        if dlq:
            dlq.append(record)
    return result


def is_single_span(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if "spans" in payload or "resourceSpans" in payload:
        return False
    return any(key in payload for key in ("span_id", "spanId", "id"))
