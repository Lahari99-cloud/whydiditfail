# OpenInference Examples

These fixtures show WDIF consuming OpenInference-style semantic attributes.

## Run

```bash
wdif analyze examples/openinference/semantic_trace.json --json
wdif snapshot examples/openinference/semantic_trace.json --output reports/openinference_semantic.wdif
wdif replay reports/openinference_semantic.wdif
```

## What This Covers

- `openinference.span.kind`
- retriever documents
- LLM prompt and output fields
- retriever-to-answer causal diagnosis
