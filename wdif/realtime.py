from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from wdif.config import WdifConfig, load_config
from wdif.engine import DiagnosticEngine
from wdif.ingestion import DeadLetterQueue, DeadLetterRecord, TraceStagingBuffer, is_single_span
from wdif.models import FailureDiagnostic, TraceSpan
from wdif.parser import OpenInferenceParser


@dataclass
class WatchStats:
    lines_read: int = 0
    payloads_seen: int = 0
    traces_flushed: int = 0
    traces_evicted: int = 0
    spans_seen: int = 0
    dead_letter_count: int = 0
    diagnostics: list[FailureDiagnostic] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lines_read": self.lines_read,
            "payloads_seen": self.payloads_seen,
            "traces_flushed": self.traces_flushed,
            "traces_evicted": self.traces_evicted,
            "spans_seen": self.spans_seen,
            "dead_letter_count": self.dead_letter_count,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }


class LiveTraceWatcher:
    """Tails JSONL telemetry and periodically flushes staged traces by idle time."""

    def __init__(
        self,
        trace_file: Path,
        config: WdifConfig | None = None,
        dlq_path: Path | None = None,
        flush_after_seconds: float = 2.0,
        poll_interval_seconds: float = 0.25,
    ):
        self.trace_file = trace_file
        self.config = config or WdifConfig.default()
        self.dlq = DeadLetterQueue(dlq_path) if dlq_path else None
        self.flush_after_seconds = flush_after_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.max_active_traces = self.config.ingestion.max_active_traces
        self.max_trace_spans = self.config.ingestion.max_trace_spans
        self.max_trace_age_seconds = self.config.ingestion.max_trace_age_seconds
        self.parser = OpenInferenceParser()
        self.engine = DiagnosticEngine(config=self.config)
        self._staged: dict[str, list[dict[str, Any]]] = {}
        self._first_seen: dict[str, float] = {}
        self._last_seen: dict[str, float] = {}
        self._payloads: list[dict[str, Any]] = []

    def watch(
        self,
        max_seconds: float | None = None,
        on_diagnostics: Callable[[list[FailureDiagnostic]], None] | None = None,
        start_at_end: bool = False,
    ) -> WatchStats:
        stats = WatchStats()
        started = time.monotonic()
        self.trace_file.parent.mkdir(parents=True, exist_ok=True)
        self.trace_file.touch(exist_ok=True)

        offset = self.trace_file.stat().st_size if start_at_end else 0

        while True:
            now = time.monotonic()
            with self.trace_file.open("r", encoding="utf-8") as handle:
                handle.seek(offset)
                while True:
                    line = handle.readline()
                    if not line:
                        break
                    offset = handle.tell()
                    self._process_line(line, stats, now)

            diagnostics = self._flush_bounded(stats, now)
            if diagnostics and on_diagnostics:
                on_diagnostics(diagnostics)

            if max_seconds is not None and now - started >= max_seconds:
                diagnostics = self._flush_all(stats)
                if diagnostics and on_diagnostics:
                    on_diagnostics(diagnostics)
                return stats

            time.sleep(self.poll_interval_seconds)

    def _process_line(self, line: str, stats: WatchStats, now: float) -> None:
        if not line.strip():
            return
        stats.lines_read += 1
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            stats.dead_letter_count += 1
            record = DeadLetterRecord(
                source=str(self.trace_file),
                line_number=stats.lines_read,
                error=str(exc),
                raw_excerpt=line[:500],
            )
            if self.dlq:
                self.dlq.append(record)
            return

        if not isinstance(payload, dict):
            stats.dead_letter_count += 1
            if self.dlq:
                self.dlq.append(
                    DeadLetterRecord(
                        source=str(self.trace_file),
                        line_number=stats.lines_read,
                        error=f"Expected JSON object, received {type(payload).__name__}",
                        raw_excerpt=line[:500],
                    )
                )
            return

        stats.payloads_seen += 1
        if is_single_span(payload):
            trace_id = str(payload.get("trace_id") or payload.get("traceId") or "__default__")
            self._staged.setdefault(trace_id, []).append(payload)
            self._first_seen.setdefault(trace_id, now)
            self._last_seen[trace_id] = now
            stats.spans_seen += 1
        else:
            self._payloads.append(payload)

    def _flush_bounded(self, stats: WatchStats, now: float) -> list[FailureDiagnostic]:
        diagnostics: list[FailureDiagnostic] = []
        ready_reasons: dict[str, str] = {}
        for trace_id, last_seen in self._last_seen.items():
            if now - last_seen >= self.flush_after_seconds:
                ready_reasons[trace_id] = "idle"
        for trace_id, first_seen in self._first_seen.items():
            if now - first_seen >= self.max_trace_age_seconds:
                ready_reasons.setdefault(trace_id, "age")
        for trace_id, spans in self._staged.items():
            if len(spans) >= self.max_trace_spans:
                ready_reasons.setdefault(trace_id, "span_count")

        while len(self._staged) - len(ready_reasons) > self.max_active_traces:
            oldest = min(
                (trace_id for trace_id in self._staged if trace_id not in ready_reasons),
                key=lambda trace_id: self._first_seen.get(trace_id, now),
            )
            ready_reasons[oldest] = "active_trace_limit"

        for trace_id, reason in ready_reasons.items():
            spans = self._staged.pop(trace_id, None)
            if not spans:
                continue
            payload = {"spans": spans}
            self._first_seen.pop(trace_id, None)
            self._last_seen.pop(trace_id, None)
            if reason != "idle":
                stats.traces_evicted += 1
            diagnostics.extend(self._analyze_payload(payload, stats))

        if self._payloads:
            payloads = self._payloads
            self._payloads = []
            for payload in payloads:
                diagnostics.extend(self._analyze_payload(payload, stats))

        stats.diagnostics.extend(diagnostics)
        return diagnostics

    def _flush_all(self, stats: WatchStats) -> list[FailureDiagnostic]:
        diagnostics: list[FailureDiagnostic] = []
        for trace_id in list(self._staged):
            payload = {"spans": self._staged.pop(trace_id)}
            self._first_seen.pop(trace_id, None)
            self._last_seen.pop(trace_id, None)
            diagnostics.extend(self._analyze_payload(payload, stats))
        for payload in self._payloads:
            diagnostics.extend(self._analyze_payload(payload, stats))
        self._payloads = []
        stats.diagnostics.extend(diagnostics)
        return diagnostics

    def _analyze_payload(self, payload: dict[str, Any], stats: WatchStats) -> list[FailureDiagnostic]:
        roots = self.parser.parse_file_payload(payload)
        stats.traces_flushed += len(roots)
        return self.engine.analyze(roots)


def watch_file(
    trace_file: Path,
    config_path: Path | None = None,
    dlq_path: Path | None = None,
    flush_after_seconds: float = 2.0,
    poll_interval_seconds: float = 0.25,
    max_seconds: float | None = None,
    start_at_end: bool = False,
) -> WatchStats:
    watcher = LiveTraceWatcher(
        trace_file=trace_file,
        config=load_config(config_path),
        dlq_path=dlq_path,
        flush_after_seconds=flush_after_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    return watcher.watch(max_seconds=max_seconds, start_at_end=start_at_end)
