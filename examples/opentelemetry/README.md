# OpenTelemetry Examples

These fixtures show WDIF consuming OTLP-style `resourceSpans` exports with GenAI/OpenTelemetry-style attributes.

## Run

```bash
wdif analyze examples/opentelemetry/otlp_genai_trace.json --json
wdif tree examples/opentelemetry/otlp_genai_trace.json
```

## What This Covers

- `resourceSpans` / `scopeSpans` / `spans`
- OTLP attribute arrays
- `gen_ai.operation.name`
- `gen_ai.request.model`
- `input.value` and `output.value`
- low-score retrieval evidence that produces deterministic RCA output
