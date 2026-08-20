"""Immutable logical-file data model and off-thread loader."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, cast

from sase.ace.tui.graphics import artifact_file_view_mode
from sase.ace.tui.graphics._viewer_types import ArtifactViewMode
from sase.ace.tui.util.trace import tui_trace
from sase.ace.tui.relations.artifact_links import (
    ArtifactLinksSnapshot,
    empty_artifact_links_snapshot,
    load_artifact_links_snapshot,
)
from sase.core.artifact_file_query_facade import query_artifact_files
from sase.core.artifact_file_types import (
    ArtifactFile,
    ArtifactFileKind,
    coerce_artifact_file_kind,
    infer_artifact_file_kind,
)
from sase.core.artifact_ref_files_index import query_ref_file_versions


FILES_FIRST_PAGE_LIMIT = 500
FileOrigin = Literal["ref", "created", "capture"]
_VIEW_MODES: tuple[ArtifactViewMode, ...] = (
    "image",
    "markdown",
    "pdf",
    "text",
    "video",
)
_ORIGINS: tuple[FileOrigin, ...] = ("ref", "created", "capture")


@dataclass(frozen=True, slots=True)
class FileVersion:
    """One content version of a logical artifact file."""

    version_id: str
    logical_id: str
    label: str
    kind: str
    origin: FileOrigin
    origins: frozenset[FileOrigin]
    created_at: str | None
    agents: tuple[str, ...]
    projects: tuple[str, ...]
    artifact_id: str | None = None
    path: str | None = None
    source_path: str | None = None
    workspace_dir: str | None = None
    agent_artifacts_dir: str | None = None
    workflow: str | None = None
    raw_timestamp: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    mime_type: str | None = None
    vcs_repo: str | None = None
    vcs_sha: str | None = None
    vcs_relpath: str | None = None
    object_relpath: str | None = None
    sidecar_repo: str | None = None
    root_name: str | None = None
    authored_path: str | None = None

    @property
    def project(self) -> str | None:
        return self.projects[0] if self.projects else None

    @property
    def agent_name(self) -> str | None:
        return self.agents[0] if self.agents else None


@dataclass(frozen=True, slots=True)
class LogicalFile:
    """One selectable logical file row with ordered content versions."""

    logical_id: str
    label: str
    kind: str
    versions: tuple[FileVersion, ...]
    agents: tuple[str, ...]
    projects: tuple[str, ...]
    origins: frozenset[FileOrigin]
    latest_seen_at: str | None

    @property
    def latest(self) -> FileVersion:
        return self.versions[-1]


@dataclass(frozen=True, slots=True)
class FilesSnapshot:
    """One project-scoped logical-file result accepted by the UI thread."""

    rows: tuple[LogicalFile, ...]
    project: str | None
    complete: bool
    view_modes: Mapping[str, ArtifactViewMode]
    view_mode_counts: Mapping[ArtifactViewMode, int]
    origin_counts: Mapping[FileOrigin, int]
    load_error: str | None = None
    artifact_links: ArtifactLinksSnapshot = field(
        default_factory=empty_artifact_links_snapshot
    )

    def view_mode_for(self, version: FileVersion) -> ArtifactViewMode:
        return self.view_modes.get(version.version_id, "text")


def selected_file_version_to_artifact_file(version: FileVersion) -> ArtifactFile:
    """Adapt a selected logical version to the existing artifact-file renderer."""

    return ArtifactFile(
        id=version.artifact_id or version.version_id,
        label=version.label,
        kind=_artifact_file_kind(version),
        path=version.path,
        source_path=version.source_path,
        workspace_dir=version.workspace_dir,
        created_at=version.created_at,
        agent_artifacts_dir=version.agent_artifacts_dir,
        project=version.project,
        workflow=version.workflow,
        raw_timestamp=version.raw_timestamp,
        agent_name=version.agent_name,
        explicit=version.origin == "created",
        sha256=version.sha256,
        size_bytes=version.size_bytes,
        mime_type=version.mime_type,
        vcs_repo=version.vcs_repo,
        vcs_sha=version.vcs_sha,
        vcs_relpath=version.vcs_relpath,
    )


def _files_snapshot(
    rows: Sequence[LogicalFile],
    *,
    project: str | None,
    complete: bool = True,
    load_error: str | None = None,
) -> FilesSnapshot:
    accepted_rows = tuple(rows)
    view_modes: dict[str, ArtifactViewMode] = {}
    view_counts: Counter[ArtifactViewMode] = Counter()
    origin_counts: Counter[FileOrigin] = Counter()
    for row in accepted_rows:
        for origin in row.origins:
            origin_counts[origin] += 1
        for version in row.versions:
            mode = (
                artifact_file_view_mode(
                    version.path
                    or version.source_path
                    or version.vcs_relpath
                    or version.label,
                    kind=version.kind,
                )
                or "text"
            )
            view_modes[version.version_id] = mode
        view_counts[view_modes[row.latest.version_id]] += 1
    return FilesSnapshot(
        rows=accepted_rows,
        project=project,
        complete=complete,
        view_modes=MappingProxyType(view_modes),
        view_mode_counts=MappingProxyType(
            {mode: view_counts.get(mode, 0) for mode in _VIEW_MODES}
        ),
        origin_counts=MappingProxyType(
            {origin: origin_counts.get(origin, 0) for origin in _ORIGINS}
        ),
        load_error=load_error,
        artifact_links=load_artifact_links_snapshot(project),
    )


def load_files_snapshot(
    project: str | None,
    limit: int | None,
) -> FilesSnapshot:
    """Query both indexes without allowing binding failures to escape."""

    with tui_trace(
        "artifacts.files.load_snapshot",
        project=project,
        limit=limit,
    ) as trace:
        try:
            legacy_rows = query_artifact_files(project=project, limit=limit)
            ref_rows = query_ref_file_versions()
        except (ImportError, RuntimeError) as exc:
            trace["error"] = type(exc).__name__
            return _files_snapshot((), project=project, load_error=str(exc))
        rows = _merge_rows(
            legacy_rows,
            ref_rows,
            project=project,
            limit=limit,
        )
        result = _files_snapshot(
            rows,
            project=project,
            complete=limit is None or len(rows) < limit,
        )
        trace["rows"] = len(result.rows)
        return result


def _merge_rows(
    legacy_rows: Sequence[ArtifactFile],
    ref_rows: Sequence[Mapping[str, Any]],
    *,
    project: str | None,
    limit: int | None,
) -> tuple[LogicalFile, ...]:
    versions_by_identity: dict[str, list[FileVersion]] = {}
    legacy_by_artifact_id = {row.id: row for row in legacy_rows}
    sidecar_roots = _sidecar_roots()
    project_values = _project_scope_values(project)
    for logical in ref_rows:
        identity = _logical_identity(logical)
        versions = logical.get("versions")
        if not isinstance(versions, Sequence):
            continue
        for raw_version in versions:
            if not isinstance(raw_version, Mapping):
                continue
            version = _version_from_ref_row(
                logical,
                raw_version,
                legacy_by_artifact_id=legacy_by_artifact_id,
                sidecar_roots=sidecar_roots,
            )
            if project_values and set(version.projects).isdisjoint(project_values):
                continue
            versions_by_identity.setdefault(identity, []).append(version)

    for row in legacy_rows:
        version = _version_from_legacy_row(row)
        identity = version.logical_id
        versions_by_identity.setdefault(identity, []).append(version)

    logical_rows = tuple(
        _logical_file(identity, versions)
        for identity, versions in versions_by_identity.items()
        if versions
    )
    rows = tuple(
        sorted(
            logical_rows,
            key=lambda row: (_timestamp_sort(row.latest_seen_at), row.label.casefold()),
            reverse=True,
        )
    )
    return rows if limit is None else rows[:limit]


def _version_from_ref_row(
    logical: Mapping[str, Any],
    version: Mapping[str, Any],
    *,
    legacy_by_artifact_id: Mapping[str, ArtifactFile],
    sidecar_roots: Mapping[str, Path],
) -> FileVersion:
    identity = _logical_identity(logical)
    artifact_id = _str(version.get("artifact_id"))
    legacy = legacy_by_artifact_id.get(artifact_id or "")
    origin = _origin(
        _str(version.get("origin")) or _str(logical.get("origin")) or "ref"
    )
    origin_values = version.get("origins")
    origin_items = (
        tuple(item for item in origin_values if isinstance(item, str))
        if isinstance(origin_values, Sequence)
        and not isinstance(origin_values, (str, bytes))
        else ()
    )
    origins = frozenset(
        _origin(item)
        for item in (
            *origin_items,
            version.get("origin"),
            logical.get("origin"),
        )
        if isinstance(item, str)
    ) or frozenset((origin,))
    label = _label_for(identity, legacy, logical)
    sha256 = _str(version.get("sha256"))
    object_relpath = _str(version.get("object_relpath"))
    sidecar_repo = _str(version.get("sidecar_repo"))
    object_path = _object_path(sidecar_roots, sidecar_repo, object_relpath)
    return FileVersion(
        version_id=f"{identity}:{sha256 or artifact_id or _str(version.get('first_seen_at')) or 'unknown'}",
        logical_id=identity,
        label=label,
        kind=_kind_for(label, legacy, version),
        origin=origin,
        origins=origins,
        created_at=_str(version.get("first_seen_at")),
        agents=_strings(version.get("agents")),
        projects=_strings(version.get("projects")),
        artifact_id=artifact_id,
        path=legacy.path if legacy is not None else object_path,
        source_path=(
            legacy.source_path
            if legacy is not None
            else _str(logical.get("authored_path"))
        ),
        workspace_dir=None if legacy is None else legacy.workspace_dir,
        agent_artifacts_dir=None if legacy is None else legacy.agent_artifacts_dir,
        workflow=None if legacy is None else legacy.workflow,
        raw_timestamp=None if legacy is None else legacy.raw_timestamp,
        sha256=sha256,
        size_bytes=_int(version.get("size_bytes")),
        mime_type=_str(version.get("mime_type")),
        vcs_repo=None if legacy is None else legacy.vcs_repo,
        vcs_sha=None if legacy is None else legacy.vcs_sha,
        vcs_relpath=None if legacy is None else legacy.vcs_relpath,
        object_relpath=object_relpath,
        sidecar_repo=sidecar_repo,
        root_name=_str(logical.get("root_name")),
        authored_path=_str(logical.get("authored_path")),
    )


def _version_from_legacy_row(row: ArtifactFile) -> FileVersion:
    origin: FileOrigin = "created" if row.explicit else "capture"
    logical = _legacy_logical_identity(row)
    return FileVersion(
        version_id=f"{logical}:{row.sha256 or row.id}",
        logical_id=logical,
        label=row.label,
        kind=row.kind,
        origin=origin,
        origins=frozenset((origin,)),
        created_at=row.created_at,
        agents=() if row.agent_name is None else (row.agent_name,),
        projects=() if row.project is None else (row.project,),
        artifact_id=row.id,
        path=row.path,
        source_path=row.source_path,
        workspace_dir=row.workspace_dir,
        agent_artifacts_dir=row.agent_artifacts_dir,
        workflow=row.workflow,
        raw_timestamp=row.raw_timestamp,
        sha256=row.sha256,
        size_bytes=row.size_bytes,
        mime_type=row.mime_type,
        vcs_repo=row.vcs_repo,
        vcs_sha=row.vcs_sha,
        vcs_relpath=row.vcs_relpath,
    )


def _logical_file(identity: str, versions: list[FileVersion]) -> LogicalFile:
    deduped: dict[tuple[str, str | None], FileVersion] = {}
    for version in sorted(
        versions,
        key=lambda item: (_timestamp_sort(item.created_at), item.version_id),
    ):
        key = (version.logical_id, version.sha256)
        previous = deduped.get(key)
        if previous is None:
            deduped[key] = version
            continue
        deduped[key] = replace(
            previous,
            origins=previous.origins | version.origins,
            agents=_union_strings(previous.agents, version.agents),
            projects=_union_strings(previous.projects, version.projects),
        )
    ordered = tuple(deduped.values())
    latest = ordered[-1]
    return LogicalFile(
        logical_id=identity,
        label=latest.label,
        kind=latest.kind,
        versions=ordered,
        agents=_union_strings(*(version.agents for version in ordered)),
        projects=_union_strings(*(version.projects for version in ordered)),
        origins=frozenset(origin for version in ordered for origin in version.origins),
        latest_seen_at=latest.created_at,
    )


def _logical_identity(logical: Mapping[str, Any]) -> str:
    return _str(logical.get("logical_path")) or _str(logical.get("path")) or "unknown"


def _legacy_logical_identity(row: ArtifactFile) -> str:
    return row.source_path or row.vcs_relpath or row.path or row.label or row.id


def _label_for(
    identity: str,
    legacy: ArtifactFile | None,
    logical: Mapping[str, Any],
) -> str:
    if legacy is not None:
        return legacy.label
    authored = _str(logical.get("authored_path"))
    return Path(authored or identity).name or identity


def _kind_for(
    label: str,
    legacy: ArtifactFile | None,
    version: Mapping[str, Any],
) -> str:
    if legacy is not None:
        return legacy.kind
    mime = _str(version.get("mime_type")) or ""
    if "markdown" in mime:
        return "markdown"
    if mime == "application/pdf":
        return "pdf"
    if mime.startswith("image/"):
        return "image"
    return infer_artifact_file_kind(label)


def _artifact_file_kind(version: FileVersion) -> ArtifactFileKind:
    if version.kind == "file":
        return infer_artifact_file_kind(
            version.path or version.source_path or version.label
        )
    try:
        return coerce_artifact_file_kind(version.kind)
    except ValueError:
        return infer_artifact_file_kind(
            version.path or version.source_path or version.label
        )


def _origin(value: str) -> FileOrigin:
    if value in _ORIGINS:
        return cast(FileOrigin, value)
    if value == "explicit":
        return "created"
    if value == "default":
        return "capture"
    return "ref"


def _sidecar_roots() -> dict[str, Path]:
    try:
        from sase.repo_inventory import collect_repo_inventory

        inventory = collect_repo_inventory()
    except Exception:
        return {}
    roots: dict[str, Path] = {}
    for record in getattr(inventory, "records", ()):
        aliases = {
            str(getattr(record, "name", "") or ""),
            str(getattr(record, "slug", "") or ""),
        }
        candidates = [getattr(record, "path", None)]
        candidates.extend(
            getattr(clone, "path", None) for clone in getattr(record, "clones", ())
        )
        for raw in candidates:
            if not raw:
                continue
            path = Path(str(raw)).expanduser().resolve(strict=False)
            aliases.add(path.name)
            for alias in aliases:
                if alias:
                    roots.setdefault(alias, path)
    return roots


def _object_path(
    sidecar_roots: Mapping[str, Path],
    sidecar_repo: str | None,
    object_relpath: str | None,
) -> str | None:
    if not sidecar_repo or not object_relpath:
        return None
    root = sidecar_roots.get(sidecar_repo)
    if root is None:
        return None
    return str(root / object_relpath)


def _project_scope_values(project: str | None) -> set[str]:
    if project is None:
        return set()
    values = {project}
    try:
        from sase.project_display_names import load_project_ref_display_snapshot

        snapshot = load_project_ref_display_snapshot()
        key = snapshot.project_key_for_ref(project)
        label = snapshot.label_for_ref(project)
        if key:
            values.add(key)
        if label:
            values.add(label)
    except Exception:
        pass
    return values


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(
        dict.fromkeys(item for item in value if isinstance(item, str) and item)
    )


def _union_strings(*groups: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
    return tuple(result)


def _timestamp_sort(value: str | None) -> str:
    return value or ""


def _str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


__all__ = [
    "FILES_FIRST_PAGE_LIMIT",
    "FileOrigin",
    "FileVersion",
    "FilesSnapshot",
    "LogicalFile",
    "load_files_snapshot",
    "selected_file_version_to_artifact_file",
]
