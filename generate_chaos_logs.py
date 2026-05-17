from __future__ import annotations

import json
from pathlib import Path


def build_parser_chaos_logs(output_path: Path = Path("chaos_dirty_stream.jsonl")) -> None:
    huge_context = "CONTEXT_BOMB " * 60_000
    critical_doc = "ESCALATION_RUNBOOK_ID = RB-7781"
    prompt = f"{huge_context}\n{critical_doc}\n{huge_context}\nUser: identify runbook."

    valid_spans = [
        {
            "id": "chaos-child-llm",
            "trace_id": "chaos-trace-1",
            "parent_id": "chaos-root",
            "name": "gpt-context-bomb",
            "attributes": {
                "openinference.span.kind": "LLM",
                "openinference.retrieval.documents": [
                    {"id": "doc_runbook", "content": critical_doc}
                ],
            },
            "input": {"prompts": [prompt]},
            "output": {"value": "I cannot find the runbook."},
        },
        {
            "id": "chaos-root",
            "trace_id": "chaos-trace-1",
            "parent_id": None,
            "name": "chaos_root_agent",
            "attributes": {"openinference.span.kind": "CHAIN"},
        },
    ]

    malformed_line = '{"id": "broken-span", "trace_id": "chaos-trace-1", "input": {"prompt": "unterminated'

    with output_path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(valid_spans[0]) + "\n")
        handle.write(malformed_line + "\n")
        handle.write(json.dumps(valid_spans[1]) + "\n")

    print(f"Wrote parser chaos stream to {output_path}")


if __name__ == "__main__":
    build_parser_chaos_logs()
