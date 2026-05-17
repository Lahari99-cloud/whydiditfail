from __future__ import annotations

import json
import random
import time
from pathlib import Path


def build_chaos_logs(output_path: Path = Path("production_traces_dump.jsonl")) -> None:
    now = int(time.time() * 1000)

    # Sized to exceed the default 4k-token lost-in-the-middle threshold with tiktoken.
    stuffed_context = "System contextual baseline for enterprise replication telemetry. " * 1400
    critical_doc = "DATABASE_REPLICATION_PORT = 9921"
    prompt_payload = (
        f"{stuffed_context}\n"
        f"CRITICAL_CONFIG: {critical_doc}\n"
        f"{stuffed_context}\n"
        "User: Verify replication port."
    )

    messy_spans = [
        {
            "id": "agent-sub-tool-span-2",
            "trace_id": "prod-chaos-trace-001",
            "parent_id": "orchestrator-span-1",
            "name": "sql_schema_lookup",
            "start_time_ms": now + 50,
            "end_time_ms": now + 120,
            "attributes": {"openinference.span.kind": "TOOL"},
            "input": {"query": "SELECT schema_name FROM information_schema.schemata;"},
            "output": {"value": "Access Denied: Insufficient Privileges."},
        },
        {
            "id": "agent-sub-tool-span-3",
            "trace_id": "prod-chaos-trace-001",
            "parent_id": "orchestrator-span-1",
            "name": "sql_schema_lookup",
            "start_time_ms": now + 130,
            "end_time_ms": now + 200,
            "attributes": {"openinference.span.kind": "TOOL"},
            "input": {"query": "SELECT schema_name FROM information_schema.schemata;"},
            "output": {"value": "Access Denied: Insufficient Privileges."},
        },
        {
            "id": "llm-inference-core-4",
            "trace_id": "prod-chaos-trace-001",
            "parent_id": "root-chain-0",
            "name": "anthropic.claude-3-5-sonnet",
            "start_time_ms": now + 250,
            "end_time_ms": now + 1200,
            "attributes": {
                "openinference.span.kind": "LLM",
                "openinference.retrieval.documents": [
                    {"id": "doc_sec_ops_01", "content": critical_doc}
                ],
            },
            "input": {"prompts": [prompt_payload]},
            "output": {
                "value": (
                    "I am sorry, but I cannot locate the replication port in the "
                    "provided text."
                )
            },
        },
        {
            "id": "root-chain-0",
            "trace_id": "prod-chaos-trace-001",
            "parent_id": None,
            "name": "enterprise_gateway_entrypoint",
            "start_time_ms": now,
            "end_time_ms": now + 1500,
            "attributes": {"openinference.span.kind": "CHAIN"},
            "input": {"value": "Verify the replication network settings across clusters."},
        },
        {
            "id": "orchestrator-span-1",
            "trace_id": "prod-chaos-trace-001",
            "parent_id": "root-chain-0",
            "name": "routing_orchestrator_agent",
            "start_time_ms": now + 10,
            "end_time_ms": now + 240,
            "attributes": {"openinference.span.kind": "CHAIN"},
            "input": {"value": "Evaluate database readiness."},
        },
    ]

    for i in range(4, 8):
        messy_spans.append(
            {
                "id": f"agent-sub-tool-span-{i}",
                "trace_id": "prod-chaos-trace-001",
                "parent_id": "orchestrator-span-1",
                "name": "sql_schema_lookup",
                "start_time_ms": now + 200 + (i * 10),
                "end_time_ms": now + 250 + (i * 10),
                "attributes": {"openinference.span.kind": "TOOL"},
                "input": {"query": "SELECT schema_name FROM information_schema.schemata;"},
                "output": {"value": "Access Denied: Insufficient Privileges."},
            }
        )

    random.Random(991).shuffle(messy_spans)

    with output_path.open("w", encoding="utf-8") as handle:
        for span in messy_spans:
            handle.write(json.dumps(span) + "\n")

    print(f"Successfully compiled '{output_path}' with out-of-order execution spans.")


if __name__ == "__main__":
    build_chaos_logs()
