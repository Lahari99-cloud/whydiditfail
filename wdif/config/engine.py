from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wdif.models import FailureType


class ConfigError(ValueError):
    pass


@dataclass
class TokenizerPolicy:
    provider: str = "tiktoken"
    name: str = "cl100k_base"
    local_path: str | None = None


@dataclass
class HeuristicPolicy:
    enabled: bool = True
    severity: str | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class IngestionPolicy:
    dead_letter_severity: str = "WARNING"
    fail_on_dead_letters: bool = False


@dataclass
class WdifConfig:
    version: str = "1.0.0"
    tokenizer: TokenizerPolicy = field(default_factory=TokenizerPolicy)
    heuristics: dict[str, HeuristicPolicy] = field(default_factory=dict)
    ingestion: IngestionPolicy = field(default_factory=IngestionPolicy)
    exit_codes: dict[str, int] = field(
        default_factory=lambda: {"CRITICAL": 2, "WARNING": 0, "INFO": 0}
    )
    concurrency: int | None = None

    @classmethod
    def default(cls) -> "WdifConfig":
        return cls()

    def policy_for(self, failure_type: str) -> HeuristicPolicy:
        return self.heuristics.get(failure_type, HeuristicPolicy())

    def exit_code_for(self, severities: set[str]) -> int:
        code = 0
        for severity in severities:
            code = max(code, int(self.exit_codes.get(severity, 0)))
        return code

    def ingestion_exit_code(self, dead_letter_count: int) -> int:
        if dead_letter_count <= 0 or not self.ingestion.fail_on_dead_letters:
            return 0
        return self.exit_code_for({self.ingestion.dead_letter_severity})


def find_config_file(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent

    for directory in (current, *current.parents):
        for name in ("wdif.yaml", "wdif.yml", "wdif.toml"):
            candidate = directory / name
            if candidate.exists():
                return candidate
    return None


def load_config(path: Path | None = None) -> WdifConfig:
    config_path = path or find_config_file()
    if not config_path:
        return WdifConfig.default()

    raw = _load_mapping(config_path)
    config = _config_from_mapping(raw)
    validate_config(config)
    return config


def validate_config(config: WdifConfig) -> None:
    allowed_severities = {"CRITICAL", "WARNING", "INFO"}
    allowed_tokenizers = {"tiktoken", "huggingface", "regex"}
    allowed_failures = {failure.value for failure in FailureType}

    if config.tokenizer.provider.lower() not in allowed_tokenizers:
        raise ConfigError(
            f"Unsupported tokenizer provider '{config.tokenizer.provider}'. "
            f"Expected one of: {sorted(allowed_tokenizers)}."
        )

    if config.concurrency is not None and int(config.concurrency) < 1:
        raise ConfigError("concurrency must be >= 1.")

    for severity, code in config.exit_codes.items():
        if severity not in allowed_severities:
            raise ConfigError(f"Unknown severity '{severity}' in exit_codes.")
        if int(code) < 0:
            raise ConfigError(f"Exit code for {severity} must be >= 0.")

    if config.ingestion.dead_letter_severity not in allowed_severities:
        raise ConfigError(
            f"Invalid ingestion.dead_letter_severity '{config.ingestion.dead_letter_severity}'."
        )

    for name, policy in config.heuristics.items():
        if name not in allowed_failures:
            raise ConfigError(f"Unknown heuristic '{name}'. Expected one of: {sorted(allowed_failures)}.")
        if policy.severity and policy.severity not in allowed_severities:
            raise ConfigError(f"Invalid severity '{policy.severity}' for heuristic {name}.")

        for option_name, option_value in policy.options.items():
            if option_name.startswith("min_") or option_name.startswith("max_"):
                _validate_number(name, option_name, option_value, minimum=0)
            if option_name in {"warning_ratio"}:
                _validate_number(name, option_name, option_value, minimum=0, maximum=1)
            if option_name.endswith("_pct"):
                _validate_number(name, option_name, option_value, minimum=0, maximum=100)


def _validate_number(
    heuristic: str,
    option_name: str,
    option_value: Any,
    minimum: float | None = None,
    maximum: float | None = None,
) -> None:
    try:
        number = float(option_value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{heuristic}.{option_name} must be numeric.") from exc
    if minimum is not None and number < minimum:
        raise ConfigError(f"{heuristic}.{option_name} must be >= {minimum}.")
    if maximum is not None and number > maximum:
        raise ConfigError(f"{heuristic}.{option_name} must be <= {maximum}.")


def _load_mapping(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".toml":
        return tomllib.loads(path.read_text(encoding="utf-8"))

    text = path.read_text(encoding="utf-8")
    try:
        import yaml

        value = yaml.safe_load(text) or {}
        return value if isinstance(value, dict) else {}
    except Exception:
        return _minimal_yaml_load(text)


def _config_from_mapping(raw: dict[str, Any]) -> WdifConfig:
    tokenizer = _tokenizer_from_raw(raw.get("tokenizer", {}))

    heuristics_raw = _normalize_heuristics(raw)
    heuristics: dict[str, HeuristicPolicy] = {}
    for name, value in heuristics_raw.items():
        if not isinstance(value, dict):
            continue
        options = {
            key: option
            for key, option in value.items()
            if key not in {"enabled", "severity"}
        }
        heuristics[str(name).upper()] = HeuristicPolicy(
            enabled=bool(value.get("enabled", True)),
            severity=str(value["severity"]).upper() if value.get("severity") else None,
            options=options,
        )

    exit_codes_raw = raw.get("exit_codes", {}) if isinstance(raw.get("exit_codes", {}), dict) else {}
    exit_codes = {"CRITICAL": 2, "WARNING": 0, "INFO": 0}
    for key, value in exit_codes_raw.items():
        exit_codes[str(key).upper()] = int(value)

    ingestion_raw = raw.get("ingestion", {}) if isinstance(raw.get("ingestion", {}), dict) else {}
    ingestion = IngestionPolicy(
        dead_letter_severity=str(ingestion_raw.get("dead_letter_severity", "WARNING")).upper(),
        fail_on_dead_letters=bool(ingestion_raw.get("fail_on_dead_letters", False)),
    )

    context_bomb_ceiling = ingestion_raw.get("max_context_bomb_characters")
    if context_bomb_ceiling is not None:
        for heuristic_name in ("LOST_IN_THE_MIDDLE", "CONTEXT_STUFFING"):
            heuristics.setdefault(heuristic_name, HeuristicPolicy()).options.setdefault(
                "max_prompt_chars",
                context_bomb_ceiling,
            )

    return WdifConfig(
        version=str(raw.get("version", "1.0.0")),
        tokenizer=tokenizer,
        heuristics=heuristics,
        ingestion=ingestion,
        exit_codes=exit_codes,
        concurrency=raw.get("concurrency"),
    )


def _tokenizer_from_raw(raw: Any) -> TokenizerPolicy:
    if isinstance(raw, str):
        return TokenizerPolicy(provider="tiktoken", name=raw)
    tokenizer_raw = raw if isinstance(raw, dict) else {}
    return TokenizerPolicy(
        provider=str(tokenizer_raw.get("provider", "tiktoken")),
        name=str(tokenizer_raw.get("name", "cl100k_base")),
        local_path=tokenizer_raw.get("local_path"),
    )


def _normalize_heuristics(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if isinstance(raw.get("heuristics"), dict):
        return raw["heuristics"]

    metrics = raw.get("metrics", {})
    if not isinstance(metrics, dict):
        return {}

    normalized: dict[str, dict[str, Any]] = {}
    for metric_name, metric_config in metrics.items():
        if not isinstance(metric_config, dict):
            continue
        canonical = _canonical_metric_name(str(metric_name))
        if not canonical:
            continue
        normalized[canonical] = _normalize_metric_options(canonical, metric_config)
    return normalized


def _canonical_metric_name(name: str) -> str | None:
    normalized = name.upper()
    aliases = {
        "LOST_IN_THE_MIDDLE": "LOST_IN_THE_MIDDLE",
        "AGENT_LOOP": "AGENT_LOOP",
        "CONTEXT_STUFFING": "CONTEXT_STUFFING",
        "RETRIEVER_MISS": "RETRIEVER_MISS",
        "TOOL_ERROR": "TOOL_ERROR",
        "UNGROUNDED_ANSWER": "UNGROUNDED_ANSWER",
        "ORPHANED_SPAN_TREE": "ORPHANED_SPAN_TREE",
    }
    return aliases.get(normalized)


def _normalize_metric_options(canonical: str, metric_config: dict[str, Any]) -> dict[str, Any]:
    value = dict(metric_config)
    if canonical == "LOST_IN_THE_MIDDLE":
        if "context_threshold_tokens" in value:
            value["min_prompt_tokens"] = value.pop("context_threshold_tokens")
        blindspot_zone = value.pop("blindspot_zone", None)
        if isinstance(blindspot_zone, list | tuple) and len(blindspot_zone) == 2:
            value["blindspot_start_pct"] = blindspot_zone[0]
            value["blindspot_end_pct"] = blindspot_zone[1]
    elif canonical == "AGENT_LOOP":
        if "max_consecutive_repeats" in value:
            value["repeated_call_threshold"] = value.pop("max_consecutive_repeats")
    elif canonical == "CONTEXT_STUFFING":
        if "max_token_budget" in value:
            value["max_context_tokens"] = value.pop("max_token_budget")
    return value


def _minimal_yaml_load(text: str) -> dict[str, Any]:
    """Small YAML subset parser for wdif.yaml when PyYAML is unavailable."""

    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if ":" not in stripped:
            continue

        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()

        while stack and indent <= stack[-1][0]:
            stack.pop()

        parent = stack[-1][1]
        if value == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _parse_scalar(value)

    return root


def _parse_scalar(value: str) -> Any:
    normalized = value.strip().strip("'\"")
    if normalized.lower() in {"true", "false"}:
        return normalized.lower() == "true"
    if normalized.lower() in {"null", "none"}:
        return None
    try:
        return int(normalized)
    except ValueError:
        pass
    try:
        return float(normalized)
    except ValueError:
        pass
    if normalized.startswith("[") or normalized.startswith("{"):
        try:
            return json.loads(normalized)
        except json.JSONDecodeError:
            return normalized
    return normalized
