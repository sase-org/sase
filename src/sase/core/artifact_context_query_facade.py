"""Rust-backed batched query facade for waited producers' artifact metadata.

This is the exact-producer counterpart to ``artifact_file_query_facade``: it
does not accept an ``agent`` name filter or perform any family/clan
membership resolution itself. Callers already resolved each named
dependency to its exact producer artifact directories (in stable producer
order) before reaching this facade; see the wait-context runtime layer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sase.core.artifact_file_types import default_artifact_files_index_path
from sase.core.rust import require_rust_binding


ARTIFACT_CONTEXT_QUERY_WIRE_SCHEMA_VERSION = 1

_OPTIONAL_STRING_FIELDS = (
    "agent_name",
    "kind",
    "label",
    "path",
    "source_path",
    "vcs_repo",
    "vcs_sha",
    "vcs_relpath",
)


@dataclass(frozen=True)
class ArtifactContextProducerGroup:
    """One resolved named dependency and its exact producer directories.

    ``agent_artifacts_dirs`` must already be in stable producer order
    (typically chronological); this facade does not reorder them.
    """

    wait_name: str
    agent_artifacts_dirs: Sequence[str]


def query_artifact_context(
    groups: Sequence[ArtifactContextProducerGroup],
    *,
    index_path: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Batch-query non-chat artifact metadata for waited producers.

    Returns plain, JSON-safe dictionaries with the documented ``wait``
    namespace fields (``wait_name``, ``agent_name``, ``ref``, ``kind``,
    ``label``, ``explicit``, ``path``, ``source_path``, ``vcs_repo``,
    ``vcs_sha``, ``vcs_relpath``), in dependency order with duplicate
    artifact IDs collapsed to their first requested dependency. An
    all-empty batch returns ``[]`` without querying the index.
    """

    _require_context_schema()
    resolved_index = (
        Path(default_artifact_files_index_path() if index_path is None else index_path)
        .expanduser()
        .resolve(strict=False)
    )
    payload = [
        {
            "wait_name": group.wait_name,
            "agent_artifacts_dirs": [str(dir_) for dir_ in group.agent_artifacts_dirs],
        }
        for group in groups
    ]
    binding = require_rust_binding("artifact_context_query")
    raw_rows = binding(str(resolved_index), payload)
    if not isinstance(raw_rows, list):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-context query "
            "result: expected a list"
        )
    return [
        _artifact_context_entry_from_wire(raw_row, row_number=index)
        for index, raw_row in enumerate(raw_rows, start=1)
    ]


def _require_context_schema() -> None:
    binding = require_rust_binding("artifact_context_query_wire_schema_version")
    version = int(binding())
    if version != ARTIFACT_CONTEXT_QUERY_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs artifact-context query wire is stale: "
            f"expected {ARTIFACT_CONTEXT_QUERY_WIRE_SCHEMA_VERSION}, got {version}"
        )


def _artifact_context_entry_from_wire(
    raw: object, *, row_number: int
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-context query row "
            f"{row_number}: expected an object"
        )
    row = cast(Mapping[str, Any], raw)

    wait_name = row.get("wait_name")
    if not isinstance(wait_name, str) or not wait_name:
        raise RuntimeError(
            "sase_core_rs returned an incomplete artifact-context query row "
            f"{row_number}: wait_name must be a non-empty string"
        )
    ref = row.get("ref")
    if not isinstance(ref, str) or not ref:
        raise RuntimeError(
            "sase_core_rs returned an incomplete artifact-context query row "
            f"{row_number}: ref must be a non-empty string"
        )
    explicit = row.get("explicit", False)
    if not isinstance(explicit, bool):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-context query row "
            f"{row_number}: explicit must be a boolean"
        )
    path = row.get("path")
    vcs_fields = tuple(
        row.get(field) for field in ("vcs_repo", "vcs_sha", "vcs_relpath")
    )
    has_path = isinstance(path, str) and bool(path)
    has_vcs = all(isinstance(value, str) and bool(value) for value in vcs_fields)
    if not has_path and not has_vcs:
        raise RuntimeError(
            "sase_core_rs returned an incomplete artifact-context query row "
            f"{row_number}: path or complete VCS provenance is required"
        )

    entry: dict[str, Any] = {
        "wait_name": wait_name,
        "ref": ref,
        "explicit": explicit,
    }
    for field in _OPTIONAL_STRING_FIELDS:
        value = row.get(field)
        if value is not None and not isinstance(value, str):
            raise RuntimeError(
                "sase_core_rs returned an incompatible artifact-context query "
                f"row {row_number}: {field} must be a string or null"
            )
        entry[field] = value
    return entry


__all__ = [
    "ARTIFACT_CONTEXT_QUERY_WIRE_SCHEMA_VERSION",
    "ArtifactContextProducerGroup",
    "query_artifact_context",
]
