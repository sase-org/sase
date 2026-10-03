"""Project discovery helpers for TUI project selection."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    normalize_project_lifecycle_state_filter,
)
from sase.project_display_names import (
    ProjectDisplayProjection,
    ProjectDisplaySnapshot,
)
from sase.workspace_provider import detect_workflow_type
from sase.workspace_provider.utils import parse_workspace_dir


def _states_for_project_records(include_states: Sequence[str] | str) -> list[str]:
    return normalize_project_lifecycle_state_filter(include_states)


def load_launchable_project_snapshot(
    projects_dir: Path | None = None,
    include_states: Sequence[str] | str = ("enabled",),
) -> tuple[ProjectDisplaySnapshot, tuple[ProjectDisplayProjection, ...]]:
    """Return one lifecycle snapshot and its launchable project projections."""
    projects_base = projects_dir or sase_projects_dir()
    if not projects_base.exists():
        return ProjectDisplaySnapshot(), ()

    records = list_project_records(
        projects_base,
        _states_for_project_records(include_states),
        include_home=True,
    )
    display_snapshot = ProjectDisplaySnapshot.from_records(records)
    projects: list[ProjectDisplayProjection] = []
    for record in records:
        if record.state != "enabled":
            continue
        if not record.project_file:
            continue
        if _is_launchable_project_file(Path(record.project_file)):
            projects.append(display_snapshot.projection_for(record.project_name))

    projects.sort(key=lambda project: project.sort_key)
    return display_snapshot, tuple(projects)


def list_launchable_projects(
    projects_dir: Path | None = None,
    include_states: Sequence[str] | str = ("enabled",),
) -> list[ProjectDisplayProjection]:
    """Return explicit canonical-key/display-label launch projections."""
    _snapshot, projects = load_launchable_project_snapshot(
        projects_dir,
        include_states,
    )
    return list(projects)


def is_launchable_project(
    project_name: str,
    projects_dir: Path | None = None,
    include_states: Sequence[str] | str = ("enabled",),
) -> bool:
    """Return whether a project entry is a valid project-scoped launch target."""
    if not project_name:
        return False

    projects_base = projects_dir or sase_projects_dir()
    records = list_project_records(
        projects_base,
        _states_for_project_records(include_states),
        include_home=True,
    )
    return is_launchable_project_with_records(project_name, records)


def is_launchable_project_with_records(
    project_name: str,
    records: Sequence[ProjectRecordWire],
    *,
    alias_map: Mapping[str, str] | None = None,
    detect_cache: DetectCache | None = None,
) -> bool:
    """Return whether *project_name* is launchable using pre-listed *records*.

    Same verdict as :func:`is_launchable_project` without re-reading the
    lifecycle inventory: aliases resolve from *records* (or a caller-supplied
    *alias_map* built from them) and provider detection memoizes into
    *detect_cache* by project-file path for the caller's lifetime. The cache
    is per-call state owned by the caller, never process-global.
    """
    if not project_name:
        return False

    try:
        if alias_map is None:
            from sase.project_alias_records import project_alias_map_from_records

            alias_map = project_alias_map_from_records(records, strict=False)
        canonical_name = alias_map.get(project_name, project_name)
    except ValueError:
        return False
    for record in records:
        if record.project_name != canonical_name or record.state != "enabled":
            continue
        if not record.project_file:
            return False
        return _is_launchable_project_file(
            Path(record.project_file), detect_cache=detect_cache
        )
    return False


#: Per-call provider-detection memo: ``(detect_fn, project_file)`` to the
#: detected workflow type (``None`` when no plugin claims the file). Keying
#: on the detect function keeps the launchability seam
#: (``sase.ace.tui.modals.project_discovery.detect_workflow_type``) and the
#: MRU provider-check seam (``sase.workspace_provider.detect_workflow_type``)
#: from sharing entries when tests mock them independently; in production
#: both names are the same function object, so one build still detects each
#: project file once.
DetectCache = dict[tuple[object, str], str | None]


def detected_workflow_type(
    project_file: Path | str,
    detect_cache: DetectCache | None = None,
    *,
    detect_fn: Callable[..., str] | None = None,
) -> str | None:
    """Return the detected workflow type for *project_file*, memoized per call.

    A caller-owned *detect_cache* maps ``(detect_fn, path)`` to the detected
    workflow type (``None`` when no plugin claims it) so one MRU build
    detects each project once. ``ValueError`` (no plugin claims the file)
    maps to ``None``; any other exception propagates as before.
    """
    fn = detect_fn if detect_fn is not None else detect_workflow_type
    key = (fn, str(project_file))
    if detect_cache is not None and key in detect_cache:
        return detect_cache[key]
    try:
        actual = fn(str(project_file))
    except ValueError:
        actual = None
    if detect_cache is not None:
        detect_cache[key] = actual
    return actual


def _is_launchable_project_file(
    project_file: Path,
    *,
    detect_cache: DetectCache | None = None,
) -> bool:
    workspace_dir = parse_workspace_dir(str(project_file))
    if not workspace_dir:
        return False

    if not Path(workspace_dir).expanduser().exists():
        return False

    return detected_workflow_type(project_file, detect_cache) is not None
