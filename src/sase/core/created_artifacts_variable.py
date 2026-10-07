"""SASE-managed ``artifacts`` output variable for created artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sase.core.agent_output_variables import update_agent_output_variable
from sase.core.artifact_file_types import ArtifactFile
from sase.core.output_variable_values import VarValue, normalize_var_value

CREATED_ARTIFACTS_OUTPUT_VARIABLE = "artifacts"
MAX_CREATED_ARTIFACT_ENTRIES = 100


class CreatedArtifactsShapeError(ValueError):
    """Existing ``artifacts`` value is not SASE-managed shape."""


class CreatedArtifactEntryTooLargeError(ValueError):
    """New artifact entry alone exceeds output-variable limits."""


@dataclass(frozen=True)
class _CreatedArtifactMerge:
    """Result of merging one created artifact into the ``artifacts`` list."""

    value: list[VarValue]
    index: int
    evicted: int


def _created_artifact_entry(
    artifact_file: ArtifactFile,
    *,
    source_retained: bool,
    bead_id: str | None,
) -> dict[str, VarValue]:
    """Build one ``artifacts`` list entry for *artifact_file*."""
    entry: dict[str, VarValue] = {
        "ref": f"file:{artifact_file.id}",
        "label": artifact_file.label,
        "kind": artifact_file.kind,
        "path": artifact_file.path,
    }
    if source_retained and artifact_file.source_path:
        entry["source_path"] = artifact_file.source_path
    if bead_id:
        entry["bead"] = bead_id
    return entry


def _merge_created_artifact_entry(
    current: VarValue | None,
    entry: dict[str, VarValue],
) -> _CreatedArtifactMerge:
    """Merge *entry* into the current ``artifacts`` value."""
    if current is None:
        candidates: list[VarValue] = []
    elif isinstance(current, list) and all(
        isinstance(item, dict)
        and isinstance(item.get("ref"), str)
        and item.get("ref") != ""
        for item in current
    ):
        candidates = list(current)
    else:
        raise CreatedArtifactsShapeError(
            "existing 'artifacts' output variable is not SASE-managed shape"
        )

    new_ref = entry.get("ref")
    new_label = entry.get("label")
    new_source = entry.get("source_path")
    has_label_source = (
        isinstance(new_label, str)
        and new_label != ""
        and isinstance(new_source, str)
        and new_source != ""
    )

    def _matches(existing: VarValue) -> bool:
        if not isinstance(existing, dict):
            return False
        if existing.get("ref") == new_ref:
            return True
        if not has_label_source:
            return False
        old_label = existing.get("label")
        old_source = existing.get("source_path")
        return (
            isinstance(old_label, str)
            and isinstance(old_source, str)
            and old_label == new_label
            and old_source == new_source
        )

    working: list[VarValue] = []
    first_index: int | None = None
    for existing in candidates:
        if _matches(existing):
            if first_index is None:
                first_index = len(working)
                working.append(entry)
            continue
        working.append(existing)
    if first_index is None:
        working.append(entry)
        first_index = len(working) - 1

    evicted = 0
    while len(working) > MAX_CREATED_ARTIFACT_ENTRIES:
        if first_index == 0:
            del working[1]
        else:
            del working[0]
            first_index -= 1
        evicted += 1

    while True:
        try:
            normalize_var_value(CREATED_ARTIFACTS_OUTPUT_VARIABLE, working)
            break
        except (TypeError, ValueError) as exc:
            if len(working) == 1:
                raise CreatedArtifactEntryTooLargeError(
                    "new artifact entry alone exceeds output-variable limits"
                ) from exc
            if first_index == 0:
                del working[1]
            else:
                del working[0]
                first_index -= 1
            evicted += 1

    return _CreatedArtifactMerge(value=working, index=first_index, evicted=evicted)


def record_created_artifact(
    artifacts_dir: Path | str,
    artifact_file: ArtifactFile,
    *,
    source_retained: bool,
    bead_id: str | None,
) -> _CreatedArtifactMerge:
    """Persist one created artifact into the ``artifacts`` output variable."""
    entry = _created_artifact_entry(
        artifact_file, source_retained=source_retained, bead_id=bead_id
    )
    holder: dict[str, _CreatedArtifactMerge] = {}

    def _update(current: VarValue | None) -> VarValue:
        merge = _merge_created_artifact_entry(current, entry)
        holder["merge"] = merge
        return merge.value

    stored = update_agent_output_variable(
        artifacts_dir, CREATED_ARTIFACTS_OUTPUT_VARIABLE, _update
    )
    merge = holder["merge"]
    assert isinstance(stored, list)
    return _CreatedArtifactMerge(value=stored, index=merge.index, evicted=merge.evicted)


__all__ = [
    "CREATED_ARTIFACTS_OUTPUT_VARIABLE",
    "MAX_CREATED_ARTIFACT_ENTRIES",
    "CreatedArtifactEntryTooLargeError",
    "CreatedArtifactsShapeError",
    "record_created_artifact",
]
