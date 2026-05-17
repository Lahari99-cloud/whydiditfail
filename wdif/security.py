from __future__ import annotations

import re
from typing import Any

SECRET_KEY_PATTERNS = (
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "password",
    "secret",
    "private_key",
)
TOKEN_SECRET_KEYS = {"access_token", "refresh_token", "id_token", "bearer_token", "session_token"}

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")


def sanitize_value(value: Any, max_string_chars: int = 1200) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if _looks_sensitive_key(str(key))
                else sanitize_value(item, max_string_chars=max_string_chars)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_value(item, max_string_chars=max_string_chars) for item in value[:50]]
    if isinstance(value, str):
        redacted = EMAIL_RE.sub("[REDACTED_EMAIL]", value)
        redacted = LONG_TOKEN_RE.sub("[REDACTED_TOKEN]", redacted)
        if len(redacted) > max_string_chars:
            return redacted[:max_string_chars] + "...[TRUNCATED]"
        return redacted
    return value


def _looks_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_").replace(".", "_")
    if normalized in TOKEN_SECRET_KEYS:
        return True
    return any(pattern in normalized for pattern in SECRET_KEY_PATTERNS)
