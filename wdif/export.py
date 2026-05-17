from __future__ import annotations

from collections import Counter
from pathlib import Path

from wdif.core.runner import TraceResult


def render_aggregate_html(results: list[TraceResult], title: str = "WhyDidItFail Export") -> str:
    failure_counts: Counter[str] = Counter()
    severity_counts: Counter[str] = Counter()
    rows = []

    for result in results:
        for diagnostic in result.diagnostics:
            failure_counts[diagnostic["failure_type"]] += 1
            severity_counts[diagnostic["severity"]] += 1
        rows.append(
            f"<tr><td>{Path(result.trace_file).name}</td><td>{result.span_count}</td>"
            f"<td>{result.diagnostic_count}</td><td>{result.critical_count}</td>"
            f"<td>{result.elapsed_seconds:.4f}s</td></tr>"
        )

    failure_bars = _bars(failure_counts)
    severity_bars = _bars(severity_counts)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{ font-family: Inter, Segoe UI, sans-serif; margin: 32px; color: #17202a; }}
    h1, h2 {{ color: #111827; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 12px; }}
    th, td {{ border-bottom: 1px solid #e5e7eb; padding: 8px; text-align: left; }}
    .bar {{ background: #e5e7eb; border-radius: 4px; margin: 8px 0; overflow: hidden; }}
    .fill {{ background: #2563eb; color: white; padding: 5px 8px; min-width: 24px; }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <p>Offline aggregate telemetry diagnostics for {len(results)} trace file(s).</p>
  <h2>Failure Taxonomy</h2>
  {failure_bars}
  <h2>Severity Routing</h2>
  {severity_bars}
  <h2>Trace Results</h2>
  <table>
    <thead><tr><th>Trace</th><th>Spans</th><th>Diagnostics</th><th>Critical</th><th>Runtime</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</body>
</html>
"""


def _bars(counter: Counter[str]) -> str:
    if not counter:
        return "<p>No diagnostics detected.</p>"
    max_count = max(counter.values())
    parts = []
    for label, count in sorted(counter.items()):
        width = max(8, int((count / max_count) * 100))
        parts.append(
            f"<div>{label}: {count}</div>"
            f"<div class='bar'><div class='fill' style='width:{width}%'>{count}</div></div>"
        )
    return "".join(parts)
