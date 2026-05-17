from __future__ import annotations

import json
from typing import Any

from wdif.ingestion import DeadLetterQueue, TraceStagingBuffer, is_single_span, read_json_stream
from wdif.models import SpanType, TraceSpan


class OpenInferenceParser:
    """Consumes OpenInference/OpenTelemetry-like spans and builds execution trees."""

    @staticmethod
    def _map_span_type(attributes: dict[str, Any]) -> SpanType:
        kind = str(attributes.get("openinference.span.kind", "")).upper()
        if kind in SpanType.__members__:
            return SpanType[kind]

        name = str(attributes.get("span.kind", "")).upper()
        if name in SpanType.__members__:
            return SpanType[name]

        otel_kind = str(attributes.get("gen_ai.operation.name", "")).upper()
        if otel_kind in {"CHAT", "TEXT_COMPLETION", "EMBEDDINGS"}:
            return SpanType.LLM

        return SpanType.UNKNOWN

    def parse_file_payload(self, payload: Any) -> list[TraceSpan]:
        if isinstance(payload, list):
            return self.parse_raw_spans(payload)

        if not isinstance(payload, dict):
            raise ValueError("Trace payload must be a JSON object or array.")

        if "spans" in payload:
            return self.parse_raw_spans(payload["spans"])

        if "resourceSpans" in payload:
            return self.parse_raw_spans(self._flatten_otlp_spans(payload))

        return self.parse_raw_spans([payload])

    def parse_raw_spans(self, raw_spans: list[dict[str, Any]]) -> list[TraceSpan]:
        span_map: dict[str, TraceSpan] = {}
        root_spans: list[TraceSpan] = []

        for raw in raw_spans:
            span_id = self._first_present(raw, "span_id", "spanId", "id")
            if not span_id:
                continue

            attributes = self._normalize_attributes(raw.get("attributes", {}))
            input_data = self._coerce_mapping(raw.get("input") or raw.get("inputs"))
            output_data = self._coerce_mapping(raw.get("output") or raw.get("outputs"))
            self._hydrate_io_from_attributes(input_data, output_data, attributes)

            span = TraceSpan(
                span_id=str(span_id),
                trace_id=self._nullable_str(
                    self._first_present(raw, "trace_id", "traceId", "traceID")
                ),
                parent_id=self._nullable_str(
                    self._first_present(raw, "parent_id", "parent_span_id", "parentSpanId")
                ),
                name=str(raw.get("name", "unnamed_span")),
                span_type=self._map_span_type(attributes),
                start_time_ms=self._coerce_time_ms(
                    self._first_present(raw, "start_time_ms", "startTimeUnixNano", "start_time")
                ),
                end_time_ms=self._coerce_time_ms(
                    self._first_present(raw, "end_time_ms", "endTimeUnixNano", "end_time")
                ),
                input_data=input_data,
                output_data=output_data,
                attributes=attributes,
            )
            span_map[span.span_id] = span

        for span in span_map.values():
            if span.parent_id and span.parent_id in span_map:
                span_map[span.parent_id].children.append(span)
            else:
                if span.parent_id:
                    span.attributes["wdif.orphaned_parent_id"] = span.parent_id
                root_spans.append(span)

        for span in span_map.values():
            span.children.sort(key=lambda child: (child.start_time_ms, child.name))

        return sorted(root_spans, key=lambda span: (span.start_time_ms, span.name))

    def iter_trace_payloads(self, trace_file, dlq_path=None) -> Any:
        """Yield trace payloads from JSON, JSONL, or optional ijson streams."""

        path = trace_file
        dlq = DeadLetterQueue(dlq_path) if dlq_path else None
        suffix = getattr(path, "suffix", "").lower()
        if suffix == ".jsonl":
            staging = TraceStagingBuffer()
            staging.extend(read_json_stream(path, dlq=dlq).payloads)
            yield from staging.flush()
            return

        with open(path, "r", encoding="utf-8") as probe:
            first_char = probe.read(1)

        try:
            import ijson

            if first_char == "[":
                with open(path, "rb") as handle:
                    for item in ijson.items(handle, "item"):
                        yield item
                return
        except Exception:
            pass

        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, list):
            for item in payload:
                yield item
        else:
            yield payload

    def _flatten_otlp_spans(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        spans: list[dict[str, Any]] = []
        for resource_span in payload.get("resourceSpans", []):
            for scope_span in resource_span.get("scopeSpans", []):
                spans.extend(scope_span.get("spans", []))
        return spans

    @staticmethod
    def _first_present(raw: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in raw and raw[key] not in (None, ""):
                return raw[key]
        return None

    @staticmethod
    def _nullable_str(value: Any) -> str | None:
        if value in (None, ""):
            return None
        return str(value)

    @staticmethod
    def _coerce_mapping(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _coerce_time_ms(value: Any) -> int:
        if value in (None, ""):
            return 0
        try:
            number = int(value)
        except (TypeError, ValueError):
            return 0
        if number > 10_000_000_000_000:
            return number // 1_000_000
        return number

    @staticmethod
    def _normalize_attributes(attributes: Any) -> dict[str, Any]:
        if isinstance(attributes, dict):
            return attributes

        normalized: dict[str, Any] = {}
        if not isinstance(attributes, list):
            return normalized

        for item in attributes:
            if not isinstance(item, dict) or "key" not in item:
                continue
            normalized[str(item["key"])] = OpenInferenceParser._otlp_value(item.get("value"))
        return normalized

    @staticmethod
    def _otlp_value(value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        for key in ("stringValue", "intValue", "doubleValue", "boolValue"):
            if key in value:
                return value[key]
        if "arrayValue" in value:
            return [OpenInferenceParser._otlp_value(v) for v in value["arrayValue"].get("values", [])]
        return value

    @staticmethod
    def _hydrate_io_from_attributes(
        input_data: dict[str, Any],
        output_data: dict[str, Any],
        attributes: dict[str, Any],
    ) -> None:
        for attr_key, target, target_key in (
            ("input.value", input_data, "value"),
            ("openinference.input.value", input_data, "value"),
            ("output.value", output_data, "value"),
            ("openinference.output.value", output_data, "value"),
            ("llm.input_messages", input_data, "messages"),
            ("llm.output_messages", output_data, "messages"),
        ):
            if attr_key in attributes and target_key not in target:
                target[target_key] = attributes[attr_key]

    @staticmethod
    def _is_single_span(payload: Any) -> bool:
        return is_single_span(payload)
