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
    spans_seen: int = 0
    dead_letter_count: int = 0
    diagnostics: list[FailureDiagnostic] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lines_read": self.lines_read,
            "payloads_seen": self.payloads_seen,
            "traces_flushed": self.traces_flushed,
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
        self.parser = OpenInferenceParser()
        self.engine = DiagnosticEngine(config=self.config)
        self._staged: dict[str, list[dict[str, Any]]] = {}
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

            diagnostics = self._flush_idle(stats, now)
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
            self._last_seen[trace_id] = now
            stats.spans_seen += 1
        else:
            self._payloads.append(payload)

    def _flush_idle(self, stats: WatchStats, now: float) -> list[FailureDiagnostic]:
        diagnostics: list[FailureDiagnostic] = []
        ready = [
            trace_id
            for trace_id, last_seen in self._last_seen.items()
            if now - last_seen >= self.flush_after_seconds
        ]
        for trace_id in ready:
            payload = {"spans": self._staged.pop(trace_id)}
            self._last_seen.pop(trace_id, None)
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
