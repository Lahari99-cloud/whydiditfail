from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from wdif.config import ConfigError, load_config
from wdif.core.runner import run_batch, run_staged_batch
from wdif.engine import DiagnosticEngine
from wdif.export import render_aggregate_html
from wdif.ingestion import DeadLetterQueue, TraceStagingBuffer, read_json_stream
from wdif.parser import OpenInferenceParser
from wdif.realtime import watch_file
from wdif.report import render_html_report, render_markdown_report

app = typer.Typer(help="Diagnose LLM, RAG, and agent failures from local trace JSON.")
console = Console()


@app.command()
def analyze(
    trace_file: Path = typer.Argument(..., exists=True, readable=True, help="JSON trace file to inspect."),
    config_file: Optional[Path] = typer.Option(None, "--config", "-c", exists=True, readable=True),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable diagnostics."),
    report: Optional[Path] = typer.Option(None, "--report", help="Write a Markdown or HTML report."),
    fail_on_critical: bool = typer.Option(False, help="Exit non-zero when a critical diagnostic is found."),
    policy_exit: bool = typer.Option(False, "--policy-exit", help="Use configured severity exit codes."),
):
    """Analyze an OpenInference/OpenTelemetry trace JSON file."""

    payload = json.loads(trace_file.read_text(encoding="utf-8"))
    roots = OpenInferenceParser().parse_file_payload(payload)
    config = _load_config_or_exit(config_file)
    diagnostics = DiagnosticEngine(config=config).analyze(roots)

    if report:
        _write_report(report, trace_file, roots, diagnostics)

    if json_output:
        console.print_json(data=[diagnostic.to_dict() for diagnostic in diagnostics])
    else:
        _render_human_report(trace_file, roots, diagnostics)

    if fail_on_critical and any(item.severity == "CRITICAL" for item in diagnostics):
        raise typer.Exit(2)
    if policy_exit:
        raise typer.Exit(config.exit_code_for({item.severity for item in diagnostics}))


@app.command()
def batch(
    trace_dir: Path = typer.Argument(..., exists=True, file_okay=False, readable=True),
    config_file: Optional[Path] = typer.Option(None, "--config", "-c", exists=True, readable=True),
    workers: Optional[int] = typer.Option(None, "--workers", "-w", min=1),
    staged: bool = typer.Option(False, "--staged", help="Group spans by trace_id across files before analysis."),
    dlq: Optional[Path] = typer.Option(None, "--dlq", help="Write malformed JSON lines to this file."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable summary."),
    fail_on_critical: bool = typer.Option(False, help="Exit non-zero when any file has a critical diagnostic."),
    policy_exit: bool = typer.Option(False, "--policy-exit", help="Use configured severity exit codes."),
):
    """Analyze every JSON trace in a directory."""

    config = _load_config_or_exit(config_file)
    trace_files = sorted(trace_dir.glob("*.json")) + sorted(trace_dir.glob("*.jsonl"))
    if staged:
        staged_result = run_staged_batch(trace_files, config_file, dlq_path=dlq)
        summary = [staged_result.__dict__]
    else:
        batch_result = run_batch(trace_files, config_file, workers=workers)
        summary = [result.__dict__ for result in batch_result.results]

    if json_output:
        console.print_json(data=summary)
    else:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Trace")
        table.add_column("Diagnostics", justify="right")
        table.add_column("Critical", justify="right")
        for item in summary:
            table.add_row(
                item["trace_file"],
                str(item["diagnostic_count"]),
                str(item["critical_count"]),
            )
        console.print(table)

    if fail_on_critical and any(item["critical_count"] for item in summary):
        raise typer.Exit(2)
    if policy_exit:
        severities = {
            diagnostic["severity"]
            for item in summary
            for diagnostic in item["diagnostics"]
        }
        diagnostic_exit = config.exit_code_for(severities)
        ingestion_exit = max(config.ingestion_exit_code(item.get("dead_letter_count", 0)) for item in summary)
        raise typer.Exit(max(diagnostic_exit, ingestion_exit))


@app.command()
def stream(
    trace_file: Path = typer.Argument(..., exists=True, readable=True),
    config_file: Optional[Path] = typer.Option(None, "--config", "-c", exists=True, readable=True),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable diagnostics."),
    report: Optional[Path] = typer.Option(None, "--report", help="Write a Markdown or HTML report."),
    dlq: Optional[Path] = typer.Option(None, "--dlq", help="Write malformed JSON lines to this file."),
    policy_exit: bool = typer.Option(False, "--policy-exit", help="Use configured severity and ingestion exit codes."),
):
    """Stream JSON/JSONL trace payloads without loading the entire collection at once."""

    parser = OpenInferenceParser()
    config = _load_config_or_exit(config_file)
    engine = DiagnosticEngine(config=config)
    all_diagnostics = []
    all_roots = []
    dead_letter_count = 0

    staging = TraceStagingBuffer()
    read_result = read_json_stream(trace_file, DeadLetterQueue(dlq) if dlq else None)
    dead_letter_count += len(read_result.dead_letters)
    staging.extend(read_result.payloads)

    payloads = staging.flush()
    for payload in payloads:
        roots = parser.parse_file_payload(payload)
        all_roots.extend(roots)
        all_diagnostics.extend(engine.analyze(roots))

    if report:
        _write_report(report, trace_file, all_roots, all_diagnostics)

    if json_output:
        console.print_json(
            data={
                "ingestion": {
                    "trace_payloads": len(payloads),
                    "dead_letter_count": dead_letter_count,
                    "dlq_path": str(dlq) if dlq else None,
                },
                "diagnostics": [diagnostic.to_dict() for diagnostic in all_diagnostics],
            }
        )
    else:
        _render_human_report(
            trace_file,
            all_roots,
            all_diagnostics,
            payload_count=len(payloads),
            dead_letter_count=dead_letter_count,
        )

    if policy_exit:
        diagnostic_exit = config.exit_code_for({diagnostic.severity for diagnostic in all_diagnostics})
        ingestion_exit = config.ingestion_exit_code(dead_letter_count)
        raise typer.Exit(max(diagnostic_exit, ingestion_exit))


@app.command()
def watch(
    trace_file: Path = typer.Argument(..., help="JSONL file to tail for live telemetry."),
    config_file: Optional[Path] = typer.Option(None, "--config", "-c", exists=True, readable=True),
    dlq: Optional[Path] = typer.Option(None, "--dlq", help="Write malformed JSON lines to this file."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable watch summary on exit."),
    flush_after_seconds: float = typer.Option(2.0, "--flush-after", min=0.1),
    poll_interval_seconds: float = typer.Option(0.25, "--poll-interval", min=0.05),
    max_seconds: Optional[float] = typer.Option(None, "--max-seconds", min=0.1),
    start_at_end: bool = typer.Option(False, "--start-at-end", help="Only process lines appended after startup."),
    policy_exit: bool = typer.Option(False, "--policy-exit", help="Use configured severity and ingestion exit codes."),
):
    """Tail a JSONL file and analyze traces as spans arrive in near real time."""

    config = _load_config_or_exit(config_file)
    stats = watch_file(
        trace_file=trace_file,
        config_path=config_file,
        dlq_path=dlq,
        flush_after_seconds=flush_after_seconds,
        poll_interval_seconds=poll_interval_seconds,
        max_seconds=max_seconds,
        start_at_end=start_at_end,
    )

    if json_output:
        console.print_json(data=stats.to_dict())
    else:
        console.print(
            Panel(
                f"[bold]Lines read:[/bold] {stats.lines_read}\n"
                f"[bold]Spans seen:[/bold] {stats.spans_seen}\n"
                f"[bold]Traces flushed:[/bold] {stats.traces_flushed}\n"
                f"[bold]Dead letters:[/bold] {stats.dead_letter_count}\n"
                f"[bold]Diagnostics:[/bold] {len(stats.diagnostics)}",
                title="WhyDidItFail Watch",
                border_style="cyan",
            )
        )
        if stats.diagnostics:
            table = Table(show_header=True, header_style="bold")
            table.add_column("Severity")
            table.add_column("Failure")
            table.add_column("Trace")
            table.add_column("Span")
            table.add_column("Diagnosis")
            for diagnostic in stats.diagnostics:
                style = "red" if diagnostic.severity == "CRITICAL" else "yellow"
                table.add_row(
                    f"[{style}]{diagnostic.severity}[/{style}]",
                    diagnostic.failure_type.value,
                    diagnostic.trace_id or "",
                    diagnostic.target_span_id,
                    diagnostic.message,
                )
            console.print(table)

    if policy_exit:
        diagnostic_exit = config.exit_code_for({diagnostic.severity for diagnostic in stats.diagnostics})
        ingestion_exit = config.ingestion_exit_code(stats.dead_letter_count)
        raise typer.Exit(max(diagnostic_exit, ingestion_exit))


@app.command()
def export(
    trace_dir: Path = typer.Argument(..., exists=True, file_okay=False, readable=True),
    output: Path = typer.Option(Path("wdif_export.html"), "--output", "-o"),
    config_file: Optional[Path] = typer.Option(None, "--config", "-c", exists=True, readable=True),
    workers: Optional[int] = typer.Option(None, "--workers", "-w", min=1),
    format: str = typer.Option("html", "--format"),
):
    """Export aggregate offline telemetry analytics."""

    if format.lower() != "html":
        raise typer.BadParameter("Only html export is currently supported.")

    trace_files = sorted(trace_dir.glob("*.json")) + sorted(trace_dir.glob("*.jsonl"))
    batch_result = run_batch(trace_files, config_file, workers=workers)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_aggregate_html(batch_result.results), encoding="utf-8")
    console.print(f"[green]Exported aggregate report to {output}[/green]")


@app.command()
def tree(trace_file: Path = typer.Argument(..., exists=True, readable=True)):
    """Print the reconstructed execution tree."""

    roots = _load_roots(trace_file)
    for root in roots:
        _print_span(root)


def _render_human_report(
    trace_file: Path,
    roots,
    diagnostics,
    payload_count: int | None = None,
    dead_letter_count: int = 0,
) -> None:
    span_count = sum(len(root.walk()) for root in roots)
    payload_line = f"[bold]Trace payloads:[/bold] {payload_count}\n" if payload_count is not None else ""
    dlq_line = f"[bold]Dead letters:[/bold] {dead_letter_count}\n" if dead_letter_count else ""
    console.print(
        Panel(
            f"[bold]Trace:[/bold] {trace_file}\n"
            f"{payload_line}"
            f"{dlq_line}"
            f"[bold]Root spans:[/bold] {len(roots)}\n"
            f"[bold]Total spans:[/bold] {span_count}\n"
            f"[bold]Diagnostics:[/bold] {len(diagnostics)}",
            title="WhyDidItFail",
            border_style="cyan",
        )
    )

    if not diagnostics:
        console.print("[green]No deterministic failure signatures detected.[/green]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Severity")
    table.add_column("Failure")
    table.add_column("Span")
    table.add_column("Diagnosis")
    table.add_column("Suggested Fix")

    for diagnostic in diagnostics:
        style = "red" if diagnostic.severity == "CRITICAL" else "yellow"
        table.add_row(
            f"[{style}]{diagnostic.severity}[/{style}]",
            diagnostic.failure_type.value,
            diagnostic.target_span_id,
            diagnostic.message,
            diagnostic.suggested_fix,
        )

    console.print(table)


def _write_report(report: Path, trace_file: Path, roots, diagnostics) -> None:
    if report.suffix.lower() in {".html", ".htm"}:
        content = render_html_report(trace_file, roots, diagnostics)
    else:
        content = render_markdown_report(trace_file, roots, diagnostics)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(content, encoding="utf-8")


def _load_roots(trace_file: Path):
    parser = OpenInferenceParser()
    if trace_file.suffix.lower() == ".jsonl":
        roots = []
        for payload in parser.iter_trace_payloads(trace_file):
            roots.extend(parser.parse_file_payload(payload))
        return roots

    payload = json.loads(trace_file.read_text(encoding="utf-8"))
    return parser.parse_file_payload(payload)


def _load_config_or_exit(config_file: Optional[Path]):
    try:
        return load_config(config_file)
    except ConfigError as exc:
        console.print(f"[red]Invalid wdif config:[/red] {exc}")
        raise typer.Exit(64) from exc


def _print_span(span, indent: int = 0) -> None:
    prefix = "  " * indent
    console.print(
        f"{prefix}[bold]{span.name}[/bold] "
        f"({span.span_type.value}, id={span.span_id}, latency={span.latency_ms}ms)"
    )
    for child in span.children:
        _print_span(child, indent + 1)


def main(argv: Optional[list[str]] = None) -> None:
    app(args=argv)


if __name__ == "__main__":
    app()
