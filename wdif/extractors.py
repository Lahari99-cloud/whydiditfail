from __future__ import annotations

import json
from typing import Any

from wdif.models import TraceSpan


def extract_prompt(span: TraceSpan) -> str:
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


def extract_output_text(span: TraceSpan) -> str:
    for source in (span.output_data, span.attributes):
        for key in ("value", "output.value", "openinference.output.value", "llm.output_messages"):
            value = source.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, list):
                return "\n".join(_stringify_message(item) for item in value)
    return ""


def extract_documents(span: TraceSpan) -> list[dict[str, Any]]:
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
