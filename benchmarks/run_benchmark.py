from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wdif.engine import DiagnosticEngine
from wdif.extractors import extract_prompt
from wdif.parser import OpenInferenceParser
from wdif.tokenization import TokenCounter


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, default=Path("benchmarks/synthetic_100k.json"))
    args = parser.parse_args()

    payload = json.loads(args.trace.read_text(encoding="utf-8"))
    parse_start = perf_counter()
    roots = OpenInferenceParser().parse_file_payload(payload)
    parse_seconds = perf_counter() - parse_start

    analyze_start = perf_counter()
    diagnostics = DiagnosticEngine().analyze(roots)
    analyze_seconds = perf_counter() - analyze_start

    token_counter = TokenCounter()
    token_total = 0
    for root in roots:
        for span in root.walk():
            token_total += token_counter.count(extract_prompt(span))

    span_count = sum(len(root.walk()) for root in roots)
    total_seconds = parse_seconds + analyze_seconds
    print(json.dumps({
        "trace": str(args.trace),
        "spans": span_count,
        "diagnostics": len(diagnostics),
        "parse_seconds": round(parse_seconds, 4),
        "analyze_seconds": round(analyze_seconds, 4),
        "logs_per_second": round(span_count / total_seconds, 2) if total_seconds else 0,
        "tokens_per_second": round(token_total / analyze_seconds, 2) if analyze_seconds else 0,
    }, indent=2))


if __name__ == "__main__":
    main()
