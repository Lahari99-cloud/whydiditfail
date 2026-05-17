from __future__ import annotations

import json
from typing import Any

from wdif.config.engine import ExtractionMappings
from wdif.models import TraceSpan


class SpanExtractor:
    """Extracts prompt, document, and output fields from configured or known span shapes."""

    def __init__(self, mappings: ExtractionMappings | None = None):
        self.mappings = mappings or ExtractionMappings()

    def extract_prompt(self, span: TraceSpan) -> str:
        for value in self._mapped_values(span, self.mappings.prompt):
            prompt = _coerce_prompt(value)
            if prompt:
                return prompt
        return _extract_prompt_default(span)

    def extract_output_text(self, span: TraceSpan) -> str:
        for value in self._mapped_values(span, self.mappings.output_text):
            output = _coerce_output_text(value)
            if output:
                return output
        return _extract_output_text_default(span)

    def extract_documents(self, span: TraceSpan) -> list[dict[str, Any]]:
        for value in self._mapped_values(span, self.mappings.documents):
            documents = _coerce_documents(value)
            if documents:
                return documents
        return _extract_documents_default(span)

    def extract_model_name(self, span: TraceSpan) -> str:
        for value in self._mapped_values(span, self.mappings.model_name):
            if isinstance(value, str) and value:
                return value
        for source in (span.attributes, span.input_data, span.output_data):
            for key in ("llm.model_name", "model_name", "gen_ai.request.model", "gen_ai.response.model"):
                value = source.get(key)
                if isinstance(value, str) and value:
                    return value
        return ""

    def _mapped_values(self, span: TraceSpan, paths: list[str]) -> list[Any]:
        root = {
            "input": span.input_data,
            "output": span.output_data,
            "attributes": span.attributes,
            "span": {
                "span_id": span.span_id,
                "trace_id": span.trace_id,
                "parent_id": span.parent_id,
                "name": span.name,
                "span_type": span.span_type.value,
            },
        }
        values = []
        for path in paths:
            found, value = resolve_json_path(root, path)
            if found:
                values.append(value)
        return values


DEFAULT_EXTRACTOR = SpanExtractor()


def extract_prompt(span: TraceSpan, extractor: SpanExtractor | None = None) -> str:
    return (extractor or DEFAULT_EXTRACTOR).extract_prompt(span)


def extract_output_text(span: TraceSpan, extractor: SpanExtractor | None = None) -> str:
    return (extractor or DEFAULT_EXTRACTOR).extract_output_text(span)


def extract_documents(span: TraceSpan, extractor: SpanExtractor | None = None) -> list[dict[str, Any]]:
    return (extractor or DEFAULT_EXTRACTOR).extract_documents(span)


def extract_model_name(span: TraceSpan, extractor: SpanExtractor | None = None) -> str:
    return (extractor or DEFAULT_EXTRACTOR).extract_model_name(span)


def resolve_json_path(root: Any, path: str) -> tuple[bool, Any]:
    if not path.startswith("$"):
        return False, None

    current = root
    for token in _parse_path(path):
        if isinstance(token, int):
            if not isinstance(current, list) or token >= len(current):
                return False, None
            current = current[token]
        else:
            if not isinstance(current, dict) or token not in current:
                return False, None
            current = current[token]
    return True, current


def _parse_path(path: str) -> list[str | int]:
    tokens: list[str | int] = []
    index = 1
    while index < len(path):
        char = path[index]
        if char == ".":
            index += 1
            start = index
            while index < len(path) and path[index] not in ".[":
                index += 1
            if index > start:
                tokens.append(path[start:index])
            continue
        if char == "[":
            end = path.find("]", index)
            if end == -1:
                break
            raw = path[index + 1 : end].strip()
            if (raw.startswith("'") and raw.endswith("'")) or (
                raw.startswith('"') and raw.endswith('"')
            ):
                tokens.append(raw[1:-1])
            elif raw.isdigit():
                tokens.append(int(raw))
            else:
                tokens.append(raw)
            index = end + 1
            continue
        index += 1
    return tokens


def _extract_prompt_default(span: TraceSpan) -> str:
    """Extract a prompt-like string from common OpenInference span shapes."""

    for source in (span.input_data, span.attributes):
        prompts = source.get("prompts")
        if isinstance(prompts, list) and prompts:
            return "\n".join(_stringify_message(prompt) for prompt in prompts)

        messages = source.get("messages") or source.get("llm.input_messages")
        if isinstance(messages, list) and messages:
            return "\n".join(_stringify_message(message) for message in messages)

        for key in (
            "prompt",
            "value",
            "input.value",
            "llm.prompt_template.template",
            "openinference.input.value",
        ):
            value = source.get(key)
            if isinstance(value, str) and value:
                decoded = _json_or_text(value)
                if isinstance(decoded, list):
                    return "\n".join(_stringify_message(item) for item in decoded)
                if isinstance(decoded, dict):
                    return _stringify_message(decoded)
                return value

    return ""


def _extract_output_text_default(span: TraceSpan) -> str:
    for source in (span.output_data, span.attributes):
        for key in ("value", "output.value", "openinference.output.value", "llm.output_messages"):
            value = source.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, list):
                return "\n".join(_stringify_message(item) for item in value)
    return ""


def _extract_documents_default(span: TraceSpan) -> list[dict[str, Any]]:
    for source in (span.output_data, span.input_data, span.attributes):
        for key in (
            "documents",
            "retrieved_documents",
            "openinference.retrieval.documents",
            "retrieval.documents",
        ):
            value = source.get(key)
            documents = _coerce_documents(value)
            if documents:
                return documents

    flattened = _documents_from_numbered_attributes(span.attributes)
    if flattened:
        return flattened

    return []


def _coerce_prompt(value: Any) -> str:
    if isinstance(value, str):
        decoded = _json_or_text(value)
        if decoded is not value:
            return _coerce_prompt(decoded)
        return value
    if isinstance(value, list):
        return "\n".join(_stringify_message(item) for item in value)
    if isinstance(value, dict):
        return _stringify_message(value)
    return ""


def _coerce_output_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_stringify_message(item) for item in value)
    if isinstance(value, dict):
        return _stringify_message(value)
    return ""


def _coerce_documents(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        value = _json_or_text(value)

    if not isinstance(value, list):
        return []

    documents: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            documents.append(item)
        elif isinstance(item, str):
            documents.append({"content": item})
    return documents


def _documents_from_numbered_attributes(attributes: dict[str, Any]) -> list[dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    prefix = "retrieval.documents."

    for key, value in attributes.items():
        if not key.startswith(prefix):
            continue
        rest = key[len(prefix) :]
        parts = rest.split(".", 1)
        if len(parts) != 2 or not parts[0].isdigit():
            continue
        index, field = parts
        documents.setdefault(index, {})[field] = value

    return [documents[index] for index in sorted(documents, key=int)]


def _json_or_text(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _stringify_message(value: Any) -> str:
    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        if "content" in value:
            return str(value["content"])
        if "message" in value:
            return _stringify_message(value["message"])
        if "text" in value:
            return str(value["text"])
        if "role" in value and "value" in value:
            return f"{value['role']}: {value['value']}"
        return json.dumps(value, sort_keys=True)

    return str(value)
