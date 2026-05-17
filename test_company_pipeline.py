from __future__ import annotations

import json
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from wdif.config import load_config
from wdif.engine import DiagnosticEngine
from wdif.parser import OpenInferenceParser
from wdif.report import render_markdown_report

console = Console()


def build_corporate_trace_stream() -> list[dict]:
    # Sized to exceed the default 4k-token attention threshold with real tokenizers.
    context = "System context setup for compliance routing and policy retrieval. " * 900
    mandate = "MANDATE_9: Enforce 2FA globally."
    prompt = f"{context}\n{mandate}\n{context}\nUser: List mandate 9."

    return [
        {
            "id": "span-child-tool-1",
            "parent_id": "span-orchestrator-root",
            "trace_id": "tx-prod-9921",
            "name": "internal_vector_retrieval",
            "attributes": {"openinference.span.kind": "RETRIEVER"},
            "start_time_ms": 1715975000100,
            "end_time_ms": 1715975000250,
            "input": {"query": "Fetch Q3 compliance mandates."},
            "output": {
                "documents": [
                    {"id": "doc_compliance_vault_9", "content": mandate, "score": 0.91}
                ]
            },
        },
        {
            "id": "span-child-llm-2",
            "parent_id": "span-orchestrator-root",
            "trace_id": "tx-prod-9921",
            "name": "azure-openai.gpt-4o",
            "attributes": {
                "openinference.span.kind": "LLM",
                "openinference.retrieval.documents": [
                    {"id": "doc_compliance_vault_9", "content": mandate}
                ],
            },
            "start_time_ms": 1715975000300,
            "end_time_ms": 1715975003500,
            "input": {"prompts": [prompt]},
            "output": {"value": "Error: Mandate document was not supplied."},
        },
        {
            "id": "span-orchestrator-root",
            "parent_id": None,
            "trace_id": "tx-prod-9921",
            "name": "compliance_routing_agent",
            "attributes": {"openinference.span.kind": "CHAIN"},
            "start_time_ms": 1715975000000,
            "end_time_ms": 1715975004000,
            "input": {"value": "Check Q3 database authentication status."},
        },
    ]


def write_policy_config(path: Path) -> None:
    path.write_text(
        """
tokenizer:
  provider: tiktoken
  name: cl100k_base

exit_codes:
  CRITICAL: 1
  WARNING: 0
  INFO: 0

heuristics:
  LOST_IN_THE_MIDDLE:
    enabled: true
    severity: CRITICAL
    min_prompt_tokens: 4000
    blindspot_start_pct: 20
    blindspot_end_pct: 80
  CONTEXT_STUFFING:
    enabled: true
    severity: WARNING
    max_context_tokens: 8192
    warning_ratio: 0.9
  RETRIEVER_MISS:
    enabled: true
  AGENT_LOOP:
    enabled: true
    severity: CRITICAL
  TOOL_ERROR:
    enabled: true
  UNGROUNDED_ANSWER:
    enabled: true
    severity: WARNING
""".strip(),
        encoding="utf-8",
    )


def run_corporate_ci_test() -> int:
    console.print(
        Panel.fit(
            "[bold cyan]ENTERPRISE AI PLATFORM PIPELINE RECONSTRUCTION[/bold cyan]\n"
            "Pipeline Version: v2.4.1 | Target Environment: Staging CI/CD",
            border_style="cyan",
        )
    )

    trace_file = Path("ci_telemetry_stream.jsonl")
    policy_file = Path("ci_wdif_policy.yaml")
    report_file = Path("reports/company_pipeline_report.md")

    corporate_trace_stream = build_corporate_trace_stream()
    with trace_file.open("w", encoding="utf-8") as handle:
        for span in corporate_trace_stream:
            handle.write(json.dumps(span) + "\n")

    write_policy_config(policy_file)

    console.print(
        f"Loaded [bold green]{len(corporate_trace_stream)}[/bold green] raw "
        f"OpenInference spans from `{trace_file}`."
    )
    console.print(
        "Applied corporate governance policy: "
        "[bold yellow]LOST_IN_THE_MIDDLE = CRITICAL, CRITICAL exit code = 1[/bold yellow]"
    )

    parser = OpenInferenceParser()
    config = load_config(policy_file)
    engine = DiagnosticEngine(config=config)

    roots = []
    diagnostics = []
    for payload in parser.iter_trace_payloads(trace_file):
        payload_roots = parser.parse_file_payload(payload)
        roots.extend(payload_roots)
        diagnostics.extend(engine.analyze(payload_roots))

    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(render_markdown_report(trace_file, roots, diagnostics), encoding="utf-8")

    root_id = roots[0].span_id if roots else "<missing>"
    console.print(f"Topology graph resolved. Root span: [bold]{root_id}[/bold]")
    console.print(f"Markdown remediation report written to `{report_file}`.")

    table = Table(title="CI/CD Architecture Evaluation Pass Summary", title_justify="left", show_lines=True)
    table.add_column("Heuristic Check ID", style="cyan")
    table.add_column("Configured Severity", style="magenta")
    table.add_column("Status Result", style="bold")

    for diagnostic in diagnostics:
        status = "FAILED (Gated)" if diagnostic.severity == "CRITICAL" else "FLAGGED"
        table.add_row(diagnostic.failure_type.value, diagnostic.severity, status)

    console.print()
    console.print(table)

    exit_code = config.exit_code_for({diagnostic.severity for diagnostic in diagnostics})
    if exit_code:
        blocker = next(diagnostic for diagnostic in diagnostics if diagnostic.severity == "CRITICAL")
        console.print(
            Panel(
                f"[bold white]{blocker.message}[/bold white]\n\n"
                f"[bold yellow]REMEDIATION PATCH REQUIRED:[/bold yellow]\n"
                f"{blocker.suggested_fix}",
                title="AUTOMATED PULL REQUEST DEPLOYMENT BLOCKER",
                border_style="red",
            )
        )
        console.print(
            f"[bold red]System Status Code [{exit_code}]: merge rejected by wdif policy gate.[/bold red]"
        )
    else:
        console.print("[bold green]System Status Code [0]: deployment authorized.[/bold green]")

    trace_file.unlink(missing_ok=True)
    policy_file.unlink(missing_ok=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(run_corporate_ci_test())
