from __future__ import annotations

import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from wdif.config import WdifConfig, load_config
from wdif.engine import DiagnosticEngine
from wdif.ingestion import DeadLetterQueue, TraceStagingBuffer, read_json_stream
from wdif.models import FailureDiagnostic
from wdif.parser import OpenInferenceParser


@dataclass
class TraceResult:
    trace_file: str
    diagnostic_count: int
    critical_count: int
    diagnostics: list[dict]
    elapsed_seconds: float
    span_count: int
    dead_letter_count: int = 0


@dataclass
class BatchResult:
    results: list[TraceResult]
    elapsed_seconds: float

    @property
    def diagnostic_count(self) -> int:
        return sum(result.diagnostic_count for result in self.results)

    @property
    def critical_count(self) -> int:
        return sum(result.critical_count for result in self.results)


def analyze_trace_file(trace_file: Path, config_path: Path | None = None) -> TraceResult:
    started = perf_counter()
    payload = json.loads(trace_file.read_text(encoding="utf-8"))
    roots = OpenInferenceParser().parse_file_payload(payload)
    config = load_config(config_path)
    diagnostics = DiagnosticEngine(config=config).analyze(roots)
    span_count = sum(len(root.walk()) for root in roots)
    return TraceResult(
        trace_file=str(trace_file),
        diagnostic_count=len(diagnostics),
        critical_count=sum(1 for item in diagnostics if item.severity == "CRITICAL"),
        diagnostics=[diagnostic.to_dict() for diagnostic in diagnostics],
        elapsed_seconds=perf_counter() - started,
        span_count=span_count,
        dead_letter_count=0,
    )


def run_batch(
    trace_files: list[Path],
    config_path: Path | None = None,
    workers: int | None = None,
) -> BatchResult:
    started = perf_counter()
    if not trace_files:
        return BatchResult(results=[], elapsed_seconds=0.0)

    config = load_config(config_path)
    worker_count = workers or config.concurrency or max(1, min(os.cpu_count() or 1, len(trace_files)))
    if worker_count <= 1 or len(trace_files) == 1:
        results = [analyze_trace_file(path, config_path) for path in trace_files]
        return BatchResult(results=results, elapsed_seconds=perf_counter() - started)

    results: list[TraceResult] = []
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(analyze_trace_file, trace_file, config_path): trace_file
            for trace_file in trace_files
        }
        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda item: item.trace_file)
    return BatchResult(results=results, elapsed_seconds=perf_counter() - started)


def run_staged_batch(
    trace_files: list[Path],
    config_path: Path | None = None,
    dlq_path: Path | None = None,
) -> TraceResult:
    """Analyze split JSON/JSONL logs after grouping spans by trace_id across files."""

    started = perf_counter()
    config = load_config(config_path)
    staging = TraceStagingBuffer(
        max_traces=config.ingestion.max_active_traces,
        max_spans_per_trace=config.ingestion.max_trace_spans,
    )
    dlq = DeadLetterQueue(dlq_path) if dlq_path else None
    parser = OpenInferenceParser()
    engine = DiagnosticEngine(config=config)
    dead_letter_count = 0

    for trace_file in trace_files:
        read_result = read_json_stream(trace_file, dlq=dlq)
        dead_letter_count += len(read_result.dead_letters)
        staging.extend(read_result.payloads)

    roots = []
    diagnostics = []
    for payload in staging.flush():
        payload_roots = parser.parse_file_payload(payload)
        roots.extend(payload_roots)
        diagnostics.extend(engine.analyze(payload_roots))

    span_count = sum(len(root.walk()) for root in roots)
    return TraceResult(
        trace_file="<staged-batch>",
        diagnostic_count=len(diagnostics),
        critical_count=sum(1 for item in diagnostics if item.severity == "CRITICAL"),
        diagnostics=[
            diagnostic.to_dict()
            for diagnostic in diagnostics
        ],
        elapsed_seconds=perf_counter() - started,
        span_count=span_count,
        dead_letter_count=dead_letter_count,
    )


def diagnostics_from_result(result: TraceResult) -> list[FailureDiagnostic]:
    # Kept intentionally out of the hot path; dict output is cheaper to ship across processes.
    raise NotImplementedError("TraceResult stores JSON-safe diagnostics for worker boundaries.")
