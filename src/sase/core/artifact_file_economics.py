"""Rust-backed artifact-file store economics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from sase.core.artifact_file_types import default_artifact_files_index_path
from sase.core.rust import require_rust_binding


ARTIFACT_FILE_LIFECYCLE_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ArtifactFileEconomicsGroup:
    """One grouped row/byte total."""

    key: str
    rows: int
    bytes: int


@dataclass(frozen=True)
class _ArtifactFileGenerationProjection:
    """Rows and bytes freed by retaining N generations per label."""

    keep_per_label: int
    rows_freed: int
    bytes_freed: int


@dataclass(frozen=True)
class ArtifactFileEconomics:
    """Validated artifact-store economics returned by ``sase_core_rs``."""

    schema_version: int
    total_rows: int
    explicit_rows: int
    automatic_rows: int
    vcs_backed_rows: int
    rows_missing_size: int
    total_bytes: int
    explicit_bytes: int
    automatic_bytes: int
    vcs_backed_bytes: int
    by_kind: tuple[ArtifactFileEconomicsGroup, ...]
    by_project: tuple[ArtifactFileEconomicsGroup, ...]
    by_agent: tuple[ArtifactFileEconomicsGroup, ...]
    by_agent_truncated_groups: int
    by_agent_truncated_bytes: int
    first_created_at: str | None
    last_created_at: str | None
    window_days: int
    bytes_per_day: float
    rows_per_day: float
    duplicate_digest_groups: int
    redundant_digest_rows: int
    redundant_digest_bytes: int
    distinct_labels: int
    label_generation_projections: tuple[_ArtifactFileGenerationProjection, ...]
    source_inside_workspace_rows: int
    source_inside_workspace_bytes: int

    def to_json_dict(self) -> dict[str, object]:
        """Return the stable JSON projection used by CLI consumers."""

        return asdict(self)


def artifact_file_store_economics(
    *,
    index_path: Path | str | None = None,
    project: str | None = None,
    top_n: int = 10,
    generation_projections: Sequence[int] = (1, 3, 5),
) -> ArtifactFileEconomics:
    """Aggregate artifact-store economics without mutating the index."""

    _require_lifecycle_schema()
    resolved_index = (
        Path(default_artifact_files_index_path() if index_path is None else index_path)
        .expanduser()
        .resolve(strict=False)
    )
    options = {
        "schema_version": ARTIFACT_FILE_LIFECYCLE_WIRE_SCHEMA_VERSION,
        "project": project,
        "top_n": _nonnegative_argument(top_n, "top_n"),
        "generation_projections": [
            _nonnegative_argument(value, "generation_projections")
            for value in generation_projections
        ],
    }
    binding = require_rust_binding("artifact_file_store_economics")
    return _economics_from_wire(binding(str(resolved_index), options))


def _require_lifecycle_schema() -> None:
    binding = require_rust_binding("artifact_file_lifecycle_wire_schema_version")
    version = int(binding())
    if version != ARTIFACT_FILE_LIFECYCLE_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs artifact-file lifecycle wire is stale: "
            f"expected {ARTIFACT_FILE_LIFECYCLE_WIRE_SCHEMA_VERSION}, got {version}"
        )


def _economics_from_wire(raw: object) -> ArtifactFileEconomics:
    data = _mapping(raw, "result")
    schema_version = _integer(data, "schema_version")
    if schema_version != ARTIFACT_FILE_LIFECYCLE_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-file economics result: "
            f"schema_version must be {ARTIFACT_FILE_LIFECYCLE_WIRE_SCHEMA_VERSION}"
        )
    return ArtifactFileEconomics(
        schema_version=schema_version,
        total_rows=_integer(data, "total_rows"),
        explicit_rows=_integer(data, "explicit_rows"),
        automatic_rows=_integer(data, "automatic_rows"),
        vcs_backed_rows=_integer(data, "vcs_backed_rows"),
        rows_missing_size=_integer(data, "rows_missing_size"),
        total_bytes=_integer(data, "total_bytes"),
        explicit_bytes=_integer(data, "explicit_bytes"),
        automatic_bytes=_integer(data, "automatic_bytes"),
        vcs_backed_bytes=_integer(data, "vcs_backed_bytes"),
        by_kind=_groups(data, "by_kind"),
        by_project=_groups(data, "by_project"),
        by_agent=_groups(data, "by_agent"),
        by_agent_truncated_groups=_integer(data, "by_agent_truncated_groups"),
        by_agent_truncated_bytes=_integer(data, "by_agent_truncated_bytes"),
        first_created_at=_optional_string(data, "first_created_at"),
        last_created_at=_optional_string(data, "last_created_at"),
        window_days=_integer(data, "window_days"),
        bytes_per_day=_number(data, "bytes_per_day"),
        rows_per_day=_number(data, "rows_per_day"),
        duplicate_digest_groups=_integer(data, "duplicate_digest_groups"),
        redundant_digest_rows=_integer(data, "redundant_digest_rows"),
        redundant_digest_bytes=_integer(data, "redundant_digest_bytes"),
        distinct_labels=_integer(data, "distinct_labels"),
        label_generation_projections=_projections(data),
        source_inside_workspace_rows=_integer(data, "source_inside_workspace_rows"),
        source_inside_workspace_bytes=_integer(data, "source_inside_workspace_bytes"),
    )


def _mapping(raw: object, field: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-file economics "
            f"{field}: expected an object"
        )
    return cast(Mapping[str, Any], raw)


def _integer(
    data: Mapping[str, Any],
    field: str,
    *,
    prefix: str | None = None,
) -> int:
    value = data.get(field)
    name = f"{prefix}.{field}" if prefix else field
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-file economics "
            f"result: {name} must be a non-negative integer"
        )
    return value


def _number(data: Mapping[str, Any], field: str) -> float:
    value = data.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-file economics "
            f"result: {field} must be a non-negative number"
        )
    return float(value)


def _optional_string(data: Mapping[str, Any], field: str) -> str | None:
    value = data.get(field)
    if value is not None and not isinstance(value, str):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-file economics "
            f"result: {field} must be a string or null"
        )
    return value


def _groups(
    data: Mapping[str, Any],
    field: str,
) -> tuple[ArtifactFileEconomicsGroup, ...]:
    raw_groups = data.get(field)
    if not isinstance(raw_groups, list):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-file economics "
            f"result: {field} must be a list"
        )
    groups: list[ArtifactFileEconomicsGroup] = []
    for index, raw_group in enumerate(raw_groups, start=1):
        group = _mapping(raw_group, f"{field}[{index}]")
        key = group.get("key")
        if not isinstance(key, str):
            raise RuntimeError(
                "sase_core_rs returned an incompatible artifact-file economics "
                f"result: {field}[{index}].key must be a string"
            )
        groups.append(
            ArtifactFileEconomicsGroup(
                key=key,
                rows=_integer(group, "rows", prefix=f"{field}[{index}]"),
                bytes=_integer(group, "bytes", prefix=f"{field}[{index}]"),
            )
        )
    return tuple(groups)


def _projections(
    data: Mapping[str, Any],
) -> tuple[_ArtifactFileGenerationProjection, ...]:
    field = "label_generation_projections"
    raw_projections = data.get(field)
    if not isinstance(raw_projections, list):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-file economics "
            f"result: {field} must be a list"
        )
    projections: list[_ArtifactFileGenerationProjection] = []
    for index, raw_projection in enumerate(raw_projections, start=1):
        projection = _mapping(raw_projection, f"{field}[{index}]")
        projections.append(
            _ArtifactFileGenerationProjection(
                keep_per_label=_integer(
                    projection,
                    "keep_per_label",
                    prefix=f"{field}[{index}]",
                ),
                rows_freed=_integer(
                    projection,
                    "rows_freed",
                    prefix=f"{field}[{index}]",
                ),
                bytes_freed=_integer(
                    projection,
                    "bytes_freed",
                    prefix=f"{field}[{index}]",
                ),
            )
        )
    return tuple(projections)


def _nonnegative_argument(value: int, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must contain only non-negative integers")
    return value


__all__ = [
    "ARTIFACT_FILE_LIFECYCLE_WIRE_SCHEMA_VERSION",
    "ArtifactFileEconomics",
    "ArtifactFileEconomicsGroup",
    "artifact_file_store_economics",
]
