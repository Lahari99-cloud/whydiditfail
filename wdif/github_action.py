from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

from wdif.config import load_config
from wdif.core.runner import run_batch
from wdif.engine import DiagnosticEngine
from wdif.parser import OpenInferenceParser
from wdif.report import render_markdown_report


def main() -> None:
    trace_path = Path(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else Path("traces")
    config_path = Path(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else None
    fail = (sys.argv[3].lower() == "true") if len(sys.argv) > 3 and sys.argv[3] else True

    report = _build_report(trace_path, config_path)
    _write_step_summary(report)
    _post_pr_comment(report)

    if fail:
        config = load_config(config_path)
        severities = set(_extract_severities(report))
        exit_code = config.exit_code_for(severities)
        if exit_code:
            raise SystemExit(exit_code)


def _build_report(trace_path: Path, config_path: Path | None) -> str:
    if trace_path.is_dir():
        trace_files = sorted(trace_path.glob("*.json")) + sorted(trace_path.glob("*.jsonl"))
        result = run_batch(trace_files, config_path)
        lines = [
            "# WhyDidItFail PR Trace Diagnostics",
            "",
            "| Trace | Spans | Diagnostics | Critical |",
            "| --- | ---: | ---: | ---: |",
        ]
        for item in result.results:
            lines.append(
                f"| `{Path(item.trace_file).name}` | {item.span_count} | "
                f"{item.diagnostic_count} | {item.critical_count} |"
            )
        lines.extend(["", "## Failure Taxonomy", ""])
        for item in result.results:
            for diagnostic in item.diagnostics:
                lines.extend(
                    [
                        f"### {diagnostic['failure_type']} ({diagnostic['severity']})",
                        "",
                        f"- Trace: `{Path(item.trace_file).name}`",
                        f"- Span: `{diagnostic['target_span_id']}`",
                        f"- Diagnosis: {diagnostic['message']}",
                        f"- Suggested fix: {diagnostic['suggested_fix']}",
                        "",
                    ]
                )
        return "\n".join(lines)

    payload = json.loads(trace_path.read_text(encoding="utf-8"))
    roots = OpenInferenceParser().parse_file_payload(payload)
    diagnostics = DiagnosticEngine(config=load_config(config_path)).analyze(roots)
    return render_markdown_report(trace_path, roots, diagnostics)


def _write_step_summary(report: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(report)


def _post_pr_comment(report: str) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repository = os.environ.get("GITHUB_REPOSITORY")
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not token or not repository or not event_path:
        return

    try:
        event = json.loads(Path(event_path).read_text(encoding="utf-8"))
        pr_number = event.get("pull_request", {}).get("number")
        if not pr_number:
            return
    except Exception:
        return

    url = f"https://api.github.com/repos/{repository}/issues/{pr_number}/comments"
    payload = json.dumps({"body": report[:60_000]}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "WhyDidItFail",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=10).read()
    except Exception as exc:
        print(f"Unable to post PR comment: {exc}", file=sys.stderr)


def _extract_severities(report: str) -> set[str]:
    severities = set()
    for severity in ("CRITICAL", "WARNING", "INFO"):
        if severity in report:
            severities.add(severity)
    return severities


if __name__ == "__main__":
    main()
