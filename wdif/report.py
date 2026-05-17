from __future__ import annotations

from collections import Counter
from html import escape
from pathlib import Path

from wdif.models import FailureDiagnostic, TraceSpan
from wdif.remediation import build_context_reorder_patch


def render_markdown_report(
    trace_file: Path,
    roots: list[TraceSpan],
    diagnostics: list[FailureDiagnostic],
) -> str:
    span_count = sum(len(root.walk()) for root in roots)
    counts = Counter(item.failure_type.value for item in diagnostics)
    lines = [
        "# WhyDidItFail Diagnostic Report",
        "",
        f"- Trace file: `{trace_file}`",
        f"- Root spans: `{len(roots)}`",
        f"- Total spans: `{span_count}`",
        f"- Diagnostics: `{len(diagnostics)}`",
        "",
        "## Failure Summary",
        "",
    ]

    if counts:
        for failure_type, count in sorted(counts.items()):
            lines.append(f"- `{failure_type}`: {count}")
    else:
        lines.append("- No deterministic failure signatures detected.")

    lines.extend(["", "## Findings", ""])
    if not diagnostics:
        lines.append("No findings.")
        return "\n".join(lines) + "\n"

    for idx, diagnostic in enumerate(diagnostics, start=1):
        diagnostic_dict = diagnostic.to_dict()
        lines.extend(
            [
                f"### {idx}. {diagnostic.failure_type.value} ({diagnostic.severity})",
                "",
                f"- Trace: `{diagnostic.trace_id or '<unknown>'}`",
                f"- Span: `{diagnostic.target_span_id}`",
                f"- Diagnosis: {diagnostic.message}",
                f"- Suggested fix: {diagnostic.suggested_fix}",
                f"- Metadata: `{diagnostic_dict['metadata']}`",
                "",
            ]
        )
        patch = _patch_for_diagnostic(diagnostic)
        if patch:
            lines.extend(["```diff", patch.diff, "```", ""])

    return "\n".join(lines)


def render_html_report(
    trace_file: Path,
    roots: list[TraceSpan],
    diagnostics: list[FailureDiagnostic],
) -> str:
    markdown = render_markdown_report(trace_file, roots, diagnostics)
    body = "\n".join(_markdown_line_to_html(line) for line in markdown.splitlines())
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>WhyDidItFail Report</title>
  <style>
    body {{ font-family: Inter, Segoe UI, sans-serif; margin: 40px; color: #17202a; }}
    h1, h2, h3 {{ color: #111827; }}
    code {{ background: #f3f4f6; padding: 2px 5px; border-radius: 4px; }}
    li {{ margin: 6px 0; }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""


def _markdown_line_to_html(line: str) -> str:
    escaped = escape(line)
    if escaped.startswith("# "):
        return f"<h1>{escaped[2:]}</h1>"
    if escaped.startswith("## "):
        return f"<h2>{escaped[3:]}</h2>"
    if escaped.startswith("### "):
        return f"<h3>{escaped[4:]}</h3>"
    if escaped.startswith("- "):
        return f"<li>{escaped[2:]}</li>"
    if not escaped:
        return ""
    return f"<p>{escaped}</p>"


def _patch_for_diagnostic(diagnostic: FailureDiagnostic):
    if diagnostic.failure_type.value != "LOST_IN_THE_MIDDLE":
        return None
    prompt = diagnostic.metadata.get("layout_excerpt") or diagnostic.metadata.get("prompt_excerpt")
    chunk = diagnostic.metadata.get("chunk_excerpt")
    if not prompt or not chunk:
        return None
    return build_context_reorder_patch(str(prompt), str(chunk), placement="suffix")
