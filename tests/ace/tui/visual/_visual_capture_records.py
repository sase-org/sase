"""Versioned capture records and dict serde."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from tests.ace.tui.visual._visual_capture_paths import SCHEMA_VERSION


@dataclass(frozen=True)
class ComparisonSettings:
    """Comparison kwargs and env overrides in force at capture time."""

    max_diff_pixels: int | None
    max_diff_ratio: float | None
    material_diff_threshold: int | None
    max_material_diff_pixels: int | None
    env_max_diff_ratio: str | None
    env_material_diff_threshold: str | None
    env_max_material_diff_pixels: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_diff_pixels": self.max_diff_pixels,
            "max_diff_ratio": self.max_diff_ratio,
            "material_diff_threshold": self.material_diff_threshold,
            "max_material_diff_pixels": self.max_material_diff_pixels,
            "env_max_diff_ratio": self.env_max_diff_ratio,
            "env_material_diff_threshold": self.env_material_diff_threshold,
            "env_max_material_diff_pixels": self.env_max_material_diff_pixels,
        }


@dataclass(frozen=True)
class CaptureRecord:
    """One candidate PNG captured by a visual snapshot assertion."""

    run_id: str
    worker_id: str
    sequence: int
    node_sequence: int
    artifact_id: str
    node_id: str
    snapshot_name: str
    canonical_golden_path: str
    root_identity: str
    test_file: str | None
    test_line: int | None
    source_file: str | None
    source_line: int | None
    candidate_png_relpath: str
    candidate_svg_relpath: str | None
    candidate_sha256: str
    png_width: int
    png_height: int
    comparison_settings: ComparisonSettings
    schema_version: int = SCHEMA_VERSION
    kind: str = "capture"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "run_id": self.run_id,
            "worker_id": self.worker_id,
            "sequence": self.sequence,
            "node_sequence": self.node_sequence,
            "artifact_id": self.artifact_id,
            "node_id": self.node_id,
            "snapshot_name": self.snapshot_name,
            "canonical_golden_path": self.canonical_golden_path,
            "root_identity": self.root_identity,
            "test_file": self.test_file,
            "test_line": self.test_line,
            "source_file": self.source_file,
            "source_line": self.source_line,
            "candidate_png_relpath": self.candidate_png_relpath,
            "candidate_svg_relpath": self.candidate_svg_relpath,
            "candidate_sha256": self.candidate_sha256,
            "png_width": self.png_width,
            "png_height": self.png_height,
            "comparison_settings": self.comparison_settings.to_dict(),
        }


@dataclass(frozen=True)
class WorkerSessionRecord:
    """Execution completeness evidence for one pytest worker."""

    run_id: str
    worker_id: str
    completed: bool
    collectonly: bool
    exitstatus: int | None
    collected_node_ids: tuple[str, ...]
    executed_node_ids: tuple[str, ...]
    skipped_node_ids: tuple[str, ...]
    xfailed_node_ids: tuple[str, ...]
    xpassed_node_ids: tuple[str, ...]
    failed_node_ids: tuple[str, ...]
    error_node_ids: tuple[str, ...]
    deselected_node_ids: tuple[str, ...]
    capture_count: int
    errors: tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION
    kind: str = "worker_session"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "run_id": self.run_id,
            "worker_id": self.worker_id,
            "completed": self.completed,
            "collectonly": self.collectonly,
            "exitstatus": self.exitstatus,
            "collected_node_ids": list(self.collected_node_ids),
            "executed_node_ids": list(self.executed_node_ids),
            "skipped_node_ids": list(self.skipped_node_ids),
            "xfailed_node_ids": list(self.xfailed_node_ids),
            "xpassed_node_ids": list(self.xpassed_node_ids),
            "failed_node_ids": list(self.failed_node_ids),
            "error_node_ids": list(self.error_node_ids),
            "deselected_node_ids": list(self.deselected_node_ids),
            "capture_count": self.capture_count,
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class InventoryReport:
    """Merged capture inventory and completeness evidence."""

    run_id: str
    requested_scope: str
    full_inventory: bool
    pruning_allowed: bool
    complete: bool
    session_exitstatus: int
    collectonly: bool
    reasons: tuple[str, ...]
    errors: tuple[str, ...]
    workers_expected: tuple[str, ...]
    workers_seen: tuple[str, ...]
    lost_workers: tuple[str, ...]
    captures: tuple[CaptureRecord, ...]
    worker_sessions: tuple[WorkerSessionRecord, ...]
    collected_visual_node_ids: tuple[str, ...]
    executed_visual_node_ids: tuple[str, ...]
    skipped_visual_node_ids: tuple[str, ...]
    xfailed_visual_node_ids: tuple[str, ...]
    failed_visual_node_ids: tuple[str, ...]
    deselected_visual_node_ids: tuple[str, ...]
    roots_executed: tuple[str, ...]
    schema_version: int = SCHEMA_VERSION
    kind: str = "inventory"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "run_id": self.run_id,
            "requested_scope": self.requested_scope,
            "full_inventory": self.full_inventory,
            "pruning_allowed": self.pruning_allowed,
            "complete": self.complete,
            "session_exitstatus": self.session_exitstatus,
            "collectonly": self.collectonly,
            "reasons": list(self.reasons),
            "errors": list(self.errors),
            "workers_expected": list(self.workers_expected),
            "workers_seen": list(self.workers_seen),
            "lost_workers": list(self.lost_workers),
            "captures": [record.to_dict() for record in self.captures],
            "worker_sessions": [record.to_dict() for record in self.worker_sessions],
            "collected_visual_node_ids": list(self.collected_visual_node_ids),
            "executed_visual_node_ids": list(self.executed_visual_node_ids),
            "skipped_visual_node_ids": list(self.skipped_visual_node_ids),
            "xfailed_visual_node_ids": list(self.xfailed_visual_node_ids),
            "failed_visual_node_ids": list(self.failed_visual_node_ids),
            "deselected_visual_node_ids": list(self.deselected_visual_node_ids),
            "roots_executed": list(self.roots_executed),
        }


def _capture_from_dict(raw: Mapping[str, Any]) -> CaptureRecord:
    settings_raw = raw.get("comparison_settings")
    if not isinstance(settings_raw, Mapping):
        settings_raw = {}
    return CaptureRecord(
        run_id=str(raw["run_id"]),
        worker_id=str(raw["worker_id"]),
        sequence=int(raw["sequence"]),
        node_sequence=int(raw["node_sequence"]),
        artifact_id=str(raw["artifact_id"]),
        node_id=str(raw["node_id"]),
        snapshot_name=str(raw["snapshot_name"]),
        canonical_golden_path=str(raw["canonical_golden_path"]),
        root_identity=str(raw["root_identity"]),
        test_file=_optional_str(raw.get("test_file")),
        test_line=_optional_int(raw.get("test_line")),
        source_file=_optional_str(raw.get("source_file")),
        source_line=_optional_int(raw.get("source_line")),
        candidate_png_relpath=str(raw["candidate_png_relpath"]),
        candidate_svg_relpath=_optional_str(raw.get("candidate_svg_relpath")),
        candidate_sha256=str(raw["candidate_sha256"]),
        png_width=int(raw["png_width"]),
        png_height=int(raw["png_height"]),
        comparison_settings=ComparisonSettings(
            max_diff_pixels=_optional_int(settings_raw.get("max_diff_pixels")),
            max_diff_ratio=_optional_float(settings_raw.get("max_diff_ratio")),
            material_diff_threshold=_optional_int(
                settings_raw.get("material_diff_threshold")
            ),
            max_material_diff_pixels=_optional_int(
                settings_raw.get("max_material_diff_pixels")
            ),
            env_max_diff_ratio=_optional_str(settings_raw.get("env_max_diff_ratio")),
            env_material_diff_threshold=_optional_str(
                settings_raw.get("env_material_diff_threshold")
            ),
            env_max_material_diff_pixels=_optional_str(
                settings_raw.get("env_max_material_diff_pixels")
            ),
        ),
        schema_version=int(raw.get("schema_version", SCHEMA_VERSION)),
        kind=str(raw.get("kind", "capture")),
    )


def _worker_session_from_dict(raw: Mapping[str, Any]) -> WorkerSessionRecord:
    return WorkerSessionRecord(
        run_id=str(raw["run_id"]),
        worker_id=str(raw["worker_id"]),
        completed=bool(raw["completed"]),
        collectonly=bool(raw.get("collectonly", False)),
        exitstatus=_optional_int(raw.get("exitstatus")),
        collected_node_ids=_string_tuple(raw.get("collected_node_ids")),
        executed_node_ids=_string_tuple(raw.get("executed_node_ids")),
        skipped_node_ids=_string_tuple(raw.get("skipped_node_ids")),
        xfailed_node_ids=_string_tuple(raw.get("xfailed_node_ids")),
        xpassed_node_ids=_string_tuple(raw.get("xpassed_node_ids")),
        failed_node_ids=_string_tuple(raw.get("failed_node_ids")),
        error_node_ids=_string_tuple(raw.get("error_node_ids")),
        deselected_node_ids=_string_tuple(raw.get("deselected_node_ids")),
        capture_count=int(raw.get("capture_count", 0)),
        errors=_string_tuple(raw.get("errors")),
        schema_version=int(raw.get("schema_version", SCHEMA_VERSION)),
        kind=str(raw.get("kind", "worker_session")),
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)
