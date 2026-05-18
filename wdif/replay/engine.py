from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wdif.config import WdifConfig
from wdif.config.engine import _config_from_mapping
from wdif.engine import DiagnosticEngine
from wdif.models import FailureDiagnostic, TraceSpan
from wdif.parser import OpenInferenceParser

SNAPSHOT_SCHEMA_VERSION = "wdif.snapshot.v1"


@dataclass
class ReplayPolicy:
    enabled: bool = True
    include_trace_payload: bool = True
    include_diagnostics: bool = True


@dataclass
class ReplayResult:
    snapshot_id: str
    matches_original: bool
    snapshot_hash_valid: bool
    determinism_manifest_valid: bool
    original_diagnostics: list[dict[str, Any]]
    replay_diagnostics: list[dict[str, Any]]
    diagnostic_diff: dict[str, Any]
    replay_duration_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "matches_original": self.matches_original,
            "snapshot_hash_valid": self.snapshot_hash_valid,
            "determinism_manifest_valid": self.determinism_manifest_valid,
            "diagnostic_diff": self.diagnostic_diff,
            "original_diagnostics": self.original_diagnostics,
            "replay_diagnostics": self.replay_diagnostics,
            "replay_duration_ms": self.replay_duration_ms,
        }


@dataclass
class EvidenceSnapshot:
    schema_version: str
    snapshot_id: str
    created_at_ms: int
    trace_source: str
    trace_id: str | None
    roots: list[dict[str, Any]]
    diagnostics: list[dict[str, Any]]
    config: dict[str, Any]
    determinism_manifest: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    snapshot_hash: str = ""

    def to_dict(self, include_hash: bool = True) -> dict[str, Any]:
        data = {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "created_at_ms": self.created_at_ms,
            "trace_source": self.trace_source,
            "trace_id": self.trace_id,
            "roots": self.roots,
            "diagnostics": self.diagnostics,
            "config": self.config,
            "determinism_manifest": self.determinism_manifest,
            "metadata": self.metadata,
        }
        if include_hash:
            data["snapshot_hash"] = self.snapshot_hash
            data["hash_algorithm"] = "sha256"
        return data

    def canonical_payload(self) -> str:
        return _canonical_json(self.to_dict(include_hash=False))

    def compute_hash(self) -> str:
        return hashlib.sha256(self.canonical_payload().encode("utf-8")).hexdigest()

    def validate_hash(self) -> bool:
        return bool(self.snapshot_hash) and self.compute_hash() == self.snapshot_hash

    def deserialize_roots(self) -> list[TraceSpan]:
        return [TraceSpan.from_snapshot(root) for root in self.roots]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceSnapshot":
        return cls(
            schema_version=str(data["schema_version"]),
            snapshot_id=str(data["snapshot_id"]),
            created_at_ms=int(data["created_at_ms"]),
            trace_source=str(data.get("trace_source", "")),
            trace_id=data.get("trace_id"),
            roots=list(data.get("roots", [])),
            diagnostics=list(data.get("diagnostics", [])),
            config=dict(data.get("config", {})),
            determinism_manifest=dict(data.get("determinism_manifest", {})),
            metadata=dict(data.get("metadata", {})),
            snapshot_hash=str(data.get("snapshot_hash", "")),
        )


class EvidenceSnapshotEngine:
    """Capture immutable replay evidence from parsed traces and diagnostics."""

    def __init__(self, policy: ReplayPolicy | None = None):
        self.policy = policy or ReplayPolicy()

    def capture_trace_file(
        self,
        trace_file: Path,
        config: WdifConfig | None = None,
    ) -> EvidenceSnapshot:
        roots = _load_roots(trace_file)
        return self.capture_roots(
            roots=roots,
            trace_source=str(trace_file),
            config=config or WdifConfig.default(),
        )

    def capture_roots(
        self,
        roots: list[TraceSpan],
        trace_source: str,
        config: WdifConfig | None = None,
    ) -> EvidenceSnapshot:
        if not self.policy.enabled:
            raise ValueError("Replay snapshot capture is disabled by policy.")

        config = config or WdifConfig.default()
        root_snapshots = [
            root.to_snapshot()
            for root in sorted(roots, key=lambda span: (span.start_time_ms, span.span_id))
        ]
        diagnostics = DiagnosticEngine(config=config).analyze(roots)
        canonical_diagnostics = _canonical_diagnostics(diagnostics)
        config_mapping = _config_to_mapping(config)
        snapshot = EvidenceSnapshot(
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            snapshot_id=str(uuid.uuid4()),
            created_at_ms=int(time.time() * 1000),
            trace_source=trace_source,
            trace_id=_common_trace_id(roots),
            roots=root_snapshots,
            diagnostics=canonical_diagnostics,
            config=config_mapping,
            determinism_manifest=build_determinism_manifest(
                roots=root_snapshots,
                diagnostics=canonical_diagnostics,
                config=config_mapping,
            ),
            metadata={
                "span_count": sum(len(root.walk()) for root in roots),
                "diagnostic_count": len(diagnostics),
            },
        )
        snapshot.snapshot_hash = snapshot.compute_hash()
        return snapshot

    @staticmethod
    def save_snapshot(snapshot: EvidenceSnapshot, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_canonical_json(snapshot.to_dict()) + "\n", encoding="utf-8")

    @staticmethod
    def load_snapshot(path: Path) -> EvidenceSnapshot:
        return EvidenceSnapshot.from_dict(json.loads(path.read_text(encoding="utf-8")))


class ReplayEngine:
    """Replay snapshots through the current deterministic diagnostic engine."""

    def replay(self, snapshot: EvidenceSnapshot) -> ReplayResult:
        started = time.perf_counter()
        hash_valid = snapshot.validate_hash()
        manifest_validation = validate_determinism_manifest(snapshot)
        config = _config_from_mapping(snapshot.config)
        roots = snapshot.deserialize_roots()
        replay_diagnostics = _canonical_diagnostics(DiagnosticEngine(config=config).analyze(roots))
        original_diagnostics = _canonical_diagnostic_dicts(snapshot.diagnostics)
        diff = diff_diagnostics(original_diagnostics, replay_diagnostics)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return ReplayResult(
            snapshot_id=snapshot.snapshot_id,
            matches_original=hash_valid and manifest_validation["valid"] and not diff["changed"],
            snapshot_hash_valid=hash_valid,
            determinism_manifest_valid=manifest_validation["valid"],
            original_diagnostics=original_diagnostics,
            replay_diagnostics=replay_diagnostics,
            diagnostic_diff={**diff, "determinism_manifest": manifest_validation},
            replay_duration_ms=elapsed_ms,
        )


def diff_snapshots(before: EvidenceSnapshot, after: EvidenceSnapshot) -> dict[str, Any]:
    before_diagnostics = _canonical_diagnostic_dicts(before.diagnostics)
    after_diagnostics = _canonical_diagnostic_dicts(after.diagnostics)
    diagnostic_diff = diff_diagnostics(before_diagnostics, after_diagnostics)
    before_depth = _max_propagation_depth(before_diagnostics)
    after_depth = _max_propagation_depth(after_diagnostics)
    return {
        "snapshot_a_id": before.snapshot_id,
        "snapshot_b_id": after.snapshot_id,
        "snapshot_a_hash_valid": before.validate_hash(),
        "snapshot_b_hash_valid": after.validate_hash(),
        "snapshot_a_manifest_valid": validate_determinism_manifest(before)["valid"],
        "snapshot_b_manifest_valid": validate_determinism_manifest(after)["valid"],
        "trace_id_matches": before.trace_id == after.trace_id,
        "diagnostic_diff": diagnostic_diff,
        "propagation_depth": {
            "before": before_depth,
            "after": after_depth,
            "delta": after_depth - before_depth,
        },
        "confidence_changes": _confidence_changes(before_diagnostics, after_diagnostics),
    }


def build_determinism_manifest(
    roots: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Build reproducibility evidence for replay determinism."""

    component_versions = {
        "wdif_snapshot_schema": SNAPSHOT_SCHEMA_VERSION,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "tiktoken": _package_version("tiktoken"),
        "rich": _package_version("rich"),
        "typer": _package_version("typer"),
        "pyyaml": _package_version("pyyaml"),
    }
    heuristic_versions = {
        "attention": "v1",
        "context": "v1",
        "retriever": "v1",
        "tool_error": "v1",
        "agent_loop": "v1",
        "grounding": "v1",
        "orphan": "v1",
        "ranking": "v1",
        "causal": "v1",
    }
    return {
        "manifest_version": "wdif.determinism.v1",
        "component_versions": component_versions,
        "heuristic_versions": heuristic_versions,
        "normalization_hash": _sha256(
            {
                "roots": roots,
                "config": config,
                "heuristic_versions": heuristic_versions,
            }
        ),
        "span_tree_hash": _sha256(roots),
        "diagnostics_hash": _sha256(diagnostics),
        "config_hash": _sha256(config),
        "ranking_hash": _sha256({"ranking": heuristic_versions["ranking"], "causal": heuristic_versions["causal"]}),
    }


def validate_determinism_manifest(snapshot: EvidenceSnapshot) -> dict[str, Any]:
    expected = build_determinism_manifest(
        roots=snapshot.roots,
        diagnostics=_canonical_diagnostic_dicts(snapshot.diagnostics),
        config=snapshot.config,
    )
    stored = snapshot.determinism_manifest or {}
    mismatches = {
        key: {
            "stored": stored.get(key),
            "expected": expected.get(key),
        }
        for key in (
            "normalization_hash",
            "span_tree_hash",
            "diagnostics_hash",
            "config_hash",
            "ranking_hash",
        )
        if stored.get(key) != expected.get(key)
    }
    return {
        "valid": not mismatches,
        "mismatches": mismatches,
        "stored_component_versions": stored.get("component_versions", {}),
        "current_component_versions": expected.get("component_versions", {}),
    }


def diff_diagnostics(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
) -> dict[str, Any]:
    before_by_key = {_diagnostic_key(item): item for item in before}
    after_by_key = {_diagnostic_key(item): item for item in after}
    added = sorted(set(after_by_key) - set(before_by_key))
    removed = sorted(set(before_by_key) - set(after_by_key))
    changed = []
    for key in sorted(set(before_by_key) & set(after_by_key)):
        if before_by_key[key] != after_by_key[key]:
            changed.append(key)
    return {
        "added": added,
        "removed": removed,
        "changed": changed,
        "changed_count": len(added) + len(removed) + len(changed),
    }


def _load_roots(trace_file: Path) -> list[TraceSpan]:
    parser = OpenInferenceParser()
    if trace_file.suffix.lower() == ".jsonl":
        roots = []
        for payload in parser.iter_trace_payloads(trace_file):
            roots.extend(parser.parse_file_payload(payload))
        return roots
    payload = json.loads(trace_file.read_text(encoding="utf-8"))
    return parser.parse_file_payload(payload)


def _canonical_diagnostics(diagnostics: list[FailureDiagnostic]) -> list[dict[str, Any]]:
    return _canonical_diagnostic_dicts([diagnostic.to_dict() for diagnostic in diagnostics])


def _canonical_diagnostic_dicts(diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        diagnostics,
        key=lambda item: (
            str(item.get("failure_type", "")),
            str(item.get("target_span_id", "")),
            str(item.get("trace_id", "")),
        ),
    )


def _diagnostic_key(diagnostic: dict[str, Any]) -> str:
    return "|".join(
        [
            str(diagnostic.get("trace_id") or ""),
            str(diagnostic.get("target_span_id") or ""),
            str(diagnostic.get("failure_type") or ""),
        ]
    )


def _confidence_changes(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, Any]:
    before_by_key = {_diagnostic_key(item): item for item in before}
    after_by_key = {_diagnostic_key(item): item for item in after}
    changes = {}
    for key in sorted(set(before_by_key) & set(after_by_key)):
        before_score = float(before_by_key[key].get("confidence_score", 0.0))
        after_score = float(after_by_key[key].get("confidence_score", 0.0))
        delta = round(after_score - before_score, 3)
        if delta:
            changes[key] = {"before": before_score, "after": after_score, "delta": delta}
    return changes


def _package_version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def _sha256(data: Any) -> str:
    return hashlib.sha256(_canonical_json(data).encode("utf-8")).hexdigest()


def _max_propagation_depth(diagnostics: list[dict[str, Any]]) -> int:
    depths = [
        int((diagnostic.get("metadata") or {}).get("causal_propagation_depth", 0))
        for diagnostic in diagnostics
    ]
    return max(depths, default=0)


def _common_trace_id(roots: list[TraceSpan]) -> str | None:
    trace_ids = {span.trace_id for root in roots for span in root.walk() if span.trace_id}
    return next(iter(trace_ids)) if len(trace_ids) == 1 else None


def _config_to_mapping(config: WdifConfig) -> dict[str, Any]:
    return {
        "version": config.version,
        "tokenizer": {
            "provider": config.tokenizer.provider,
            "name": config.tokenizer.name,
            "local_path": config.tokenizer.local_path,
        },
        "tokenizer_routes": [
            {
                "match": route.match,
                "provider": route.provider,
                "name": route.name,
                "local_path": route.local_path,
            }
            for route in config.tokenizer_routes
        ],
        "extraction_mappings": {
            "prompt": config.extraction_mappings.prompt,
            "documents": config.extraction_mappings.documents,
            "output_text": config.extraction_mappings.output_text,
            "model_name": config.extraction_mappings.model_name,
        },
        "heuristics": {
            name: {
                "enabled": policy.enabled,
                "severity": policy.severity,
                **policy.options,
            }
            for name, policy in sorted(config.heuristics.items())
        },
        "ingestion": {
            "dead_letter_severity": config.ingestion.dead_letter_severity,
            "fail_on_dead_letters": config.ingestion.fail_on_dead_letters,
            "max_active_traces": config.ingestion.max_active_traces,
            "max_trace_spans": config.ingestion.max_trace_spans,
            "max_trace_age_seconds": config.ingestion.max_trace_age_seconds,
        },
        "exit_codes": dict(sorted(config.exit_codes.items())),
        "concurrency": config.concurrency,
    }


def _canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
