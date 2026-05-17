from __future__ import annotations

import argparse
import json
from pathlib import Path


def synthesize_trace(span_count: int) -> dict:
    spans = [
        {
            "span_id": "root",
            "name": "benchmark_pipeline",
            "attributes": {"openinference.span.kind": "CHAIN"},
            "start_time_ms": 0,
            "end_time_ms": span_count,
        }
    ]
    for idx in range(1, span_count):
        kind = "RETRIEVER" if idx % 10 == 0 else "TOOL" if idx % 15 == 0 else "LLM"
        span = {
            "span_id": f"span_{idx}",
            "parent_id": "root",
            "name": f"{kind.lower()}_{idx}",
            "attributes": {"openinference.span.kind": kind},
            "start_time_ms": idx,
            "end_time_ms": idx + 1,
        }
        if kind == "RETRIEVER":
            span["output"] = {"documents": []}
        elif kind == "TOOL":
            span["input"] = {"query": "same" if idx % 30 == 0 else f"q_{idx}"}
        else:
            span["input"] = {"value": "short prompt"}
            span["output"] = {"value": "short answer"}
        spans.append(span)
    return {"spans": spans}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spans", type=int, default=100_000)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/synthetic_100k.json"))
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(synthesize_trace(args.spans)), encoding="utf-8")
    print(f"Wrote {args.spans} synthetic spans to {args.output}")


if __name__ == "__main__":
    main()
