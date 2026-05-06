"""Targeted unified artifact graph refresh helpers for the TUI."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from sase.core import artifact_facade
from sase.core.artifact_wire import (
    ARTIFACT_SOURCE_AGENT_ARTIFACT,
    ARTIFACT_SOURCE_AGENT_CREATED_FILE,
    ARTIFACT_SOURCE_AGENT_THOUGHT,
    ARTIFACT_SOURCE_BEAD_STORE,
    ARTIFACT_SOURCE_CHANGESPEC,
    ARTIFACT_SOURCE_COMMIT,
    ARTIFACT_SOURCE_DIRECTORY,
    ARTIFACT_SOURCE_PROJECT_FILE,
)
from sase.core.artifact_wire.models import ArtifactMutationResultWire

_AGENT_SOURCES = (
    ARTIFACT_SOURCE_AGENT_ARTIFACT,
    ARTIFACT_SOURCE_AGENT_CREATED_FILE,
    ARTIFACT_SOURCE_AGENT_THOUGHT,
)
_PROJECT_SOURCES = (
    ARTIFACT_SOURCE_PROJECT_FILE,
    ARTIFACT_SOURCE_CHANGESPEC,
    ARTIFACT_SOURCE_COMMIT,
)
_MAX_TARGETED_REFRESH_PATHS = 64


@dataclass(frozen=True)
class _ArtifactGraphRefreshTarget:
    """Normalized, dedupable rebuild target for one changed source path."""

    key: tuple[str, str]
    target_path: Path | None = None
    artifact_dir: Path | None = None
    include_sources: tuple[str, ...] = ()
    beads_dir: Path | None = None


def default_artifact_index_path() -> Path:
    """Return the default unified artifact SQLite index path."""
    return Path.home() / ".sase" / "artifacts.sqlite"


def _refresh_artifact_graph_context(
    index_path: Path | str,
    *,
    target_path: Path | str | None = None,
    artifact_dir: Path | str | None = None,
    include_sources: tuple[str, ...] = (),
    beads_dir: Path | str | None = None,
) -> ArtifactMutationResultWire:
    """Run one bounded artifact graph rebuild for a known changed context."""

    request = artifact_facade.artifact_rebuild_request(
        target_path=target_path,
        artifact_dir=artifact_dir,
        include_sources=include_sources,
        beads_dir=beads_dir,
    )
    return artifact_facade.artifact_rebuild(index_path, request)


def refresh_artifact_graph_for_missing_artifact(
    index_path: Path | str,
    artifact_id: str,
    *,
    context_path: Path | str | None = None,
    artifact_dir: Path | str | None = None,
) -> None:
    """Refresh the smallest known source for a missing panel start artifact."""

    if artifact_dir is None:
        artifact_dir = _artifact_dir_from_agent_artifact_id(artifact_id)

    if artifact_dir is not None:
        _refresh_artifact_graph_context(
            index_path,
            artifact_dir=artifact_dir,
            include_sources=_AGENT_SOURCES,
        )
        return

    if context_path is not None:
        refresh_artifact_graph_for_paths(index_path, [Path(context_path)])
        return

    # No source path was available, so refresh project-derived rows only.
    # This recovers current ChangeSpecs while avoiding agent-artifact scans.
    _refresh_artifact_graph_context(index_path, include_sources=_PROJECT_SOURCES)


def refresh_artifact_graph_for_paths(
    index_path: Path | str,
    changed_paths: Iterable[Path | str],
) -> list[ArtifactMutationResultWire]:
    """Refresh derived graph rows for a bounded set of changed source paths."""

    results: list[ArtifactMutationResultWire] = []
    for target in _iter_artifact_graph_refresh_targets(changed_paths):
        results.append(
            _refresh_artifact_graph_context(
                index_path,
                target_path=target.target_path,
                artifact_dir=target.artifact_dir,
                include_sources=target.include_sources,
                beads_dir=target.beads_dir,
            )
        )

    return results


def _iter_artifact_graph_refresh_targets(
    changed_paths: Iterable[Path | str],
) -> list[_ArtifactGraphRefreshTarget]:
    """Classify changed paths into normalized, deduped rebuild targets."""

    targets: list[_ArtifactGraphRefreshTarget] = []
    seen: set[tuple[str, str]] = set()
    for raw_path in list(changed_paths)[:_MAX_TARGETED_REFRESH_PATHS]:
        target = classify_artifact_graph_refresh_path(raw_path)
        if target is None or target.key in seen:
            continue
        seen.add(target.key)
        targets.append(target)
    return targets


def classify_artifact_graph_refresh_path(
    raw_path: Path | str,
) -> _ArtifactGraphRefreshTarget | None:
    """Return the bounded graph refresh target for one changed path."""

    path = _normalize_path(raw_path)

    artifact_dir = _artifact_dir_for_path(path)
    if artifact_dir is not None:
        artifact_dir = _normalize_path(artifact_dir)
        return _ArtifactGraphRefreshTarget(
            key=("agent", str(artifact_dir)),
            artifact_dir=artifact_dir,
            include_sources=_AGENT_SOURCES,
        )

    beads_dir = _beads_dir_for_path(path)
    if beads_dir is not None:
        beads_dir = _normalize_path(beads_dir)
        return _ArtifactGraphRefreshTarget(
            key=("beads", str(beads_dir)),
            target_path=path,
            include_sources=(ARTIFACT_SOURCE_BEAD_STORE,),
            beads_dir=beads_dir,
        )

    if path.suffix == ".gp":
        return _ArtifactGraphRefreshTarget(
            key=("project", str(path)),
            target_path=path,
            include_sources=_PROJECT_SOURCES,
        )

    if path.exists():
        return _ArtifactGraphRefreshTarget(
            key=("directory", str(path)),
            target_path=path,
            include_sources=(ARTIFACT_SOURCE_DIRECTORY,),
        )

    return None


def _artifact_dir_from_agent_artifact_id(artifact_id: str) -> Path | None:
    """Infer an artifact directory from ``agent:<project>:<workflow>:<ts>``."""

    parts = artifact_id.split(":", 3)
    if len(parts) != 4 or parts[0] != "agent":
        return None
    _, project, workflow, timestamp = parts
    if not project or not workflow or not timestamp:
        return None
    return (
        Path.home()
        / ".sase"
        / "projects"
        / project
        / "artifacts"
        / workflow
        / timestamp
    )


def _artifact_dir_for_path(path: Path) -> Path | None:
    """Return the containing ``artifacts/<workflow>/<timestamp>`` directory."""

    parts = path.parts
    for index, part in enumerate(parts):
        if part != "artifacts":
            continue
        artifact_index = index + 2
        if artifact_index < len(parts):
            return Path(*parts[: artifact_index + 1])
    return None


def _beads_dir_for_path(path: Path) -> Path | None:
    """Return the containing ``sdd/beads`` directory for a bead JSONL path."""

    parts = path.parts
    for index in range(len(parts) - 1):
        if parts[index] == "sdd" and parts[index + 1] == "beads":
            return Path(*parts[: index + 2])
    if path.name == "issues.jsonl":
        parent = path.parent
        if parent.name == "beads":
            return parent
    return None


def _normalize_path(raw_path: Path | str) -> Path:
    path = Path(raw_path).expanduser()
    try:
        return path.resolve(strict=False)
    except OSError:
        return path.absolute()
