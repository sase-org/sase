"""Project lifecycle queries and mutations behind ``sase project``."""

from __future__ import annotations

import shutil
from pathlib import Path

from sase.ace.patch import patch_lock, write_patch_atomic
from sase.ace.patch.project_spec_path import preferred_project_spec_path
from sase.running_field._model import WorkspaceClaim
from sase.core.agent_launch_claims import list_workspace_claims_from_content
from sase.core.paths import is_valid_sase_project_name, sase_projects_dir
from sase.core.project_lifecycle_facade import (
    apply_project_lifecycle_update,
    list_project_records,
)
from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_STATES,
    ProjectRecordWire,
    is_disabled_project_lifecycle_state,
    normalize_project_lifecycle_state,
    normalize_project_lifecycle_state_filter,
)
from sase.project_aliases import ProjectAliasError, resolve_project_alias_ref

_ALL_STATES = tuple(PROJECT_LIFECYCLE_STATES)
_LIVE_ARTIFACT_MARKERS = ("running.json", "waiting.json", "pending_question.json")


class _ProjectLifecycleError(RuntimeError):
    """Base class for project lifecycle command failures."""


class _ProjectLifecycleNotFoundError(_ProjectLifecycleError):
    """Raised when a requested project cannot be resolved."""


class _ProjectLifecycleBlockedError(_ProjectLifecycleError):
    """Raised when a lifecycle mutation is blocked by live work."""

    def __init__(
        self,
        project: str,
        state: str,
        claims: list[WorkspaceClaim],
        markers: list[Path],
    ) -> None:
        self.project = project
        self.state = state
        self.claims = claims
        self.markers = markers
        pieces: list[str] = []
        if claims:
            pieces.append(f"{len(claims)} RUNNING claim(s)")
        if markers:
            pieces.append(f"{len(markers)} live artifact marker(s)")
        live_summary = ", ".join(pieces) if pieces else "live work"
        if state == "delete":
            action = "remove live work before deleting it"
        else:
            action = f"pass --force to set state to {state}"
        super().__init__(f"project '{project}' has {live_summary}; {action}")


ProjectLifecycleError = _ProjectLifecycleError
ProjectLifecycleNotFoundError = _ProjectLifecycleNotFoundError
ProjectLifecycleBlockedError = _ProjectLifecycleBlockedError


def _canonical_project_ref(
    project: str,
    projects_root: Path | None = None,
) -> str:
    if not is_valid_sase_project_name(project):
        raise _ProjectLifecycleError(f"invalid project name: {project!r}")
    root = (
        projects_root.expanduser() if projects_root is not None else sase_projects_dir()
    )
    try:
        return resolve_project_alias_ref(project, root)
    except (ProjectAliasError, ValueError) as exc:
        raise _ProjectLifecycleError(str(exc)) from exc


def _invalidate_project_identity(projects_root: Path | None = None) -> None:
    from sase.project_display_names import invalidate_project_display_snapshot

    invalidate_project_display_snapshot(projects_root)


def get_project_record(
    project: str,
    *,
    projects_only: bool = True,
) -> ProjectRecordWire:
    """Return the lifecycle record for *project*, resolving aliases first."""
    canonical_project = _canonical_project_ref(project)

    records = list_project_records(
        sase_projects_dir(),
        list(_ALL_STATES),
        include_home=True,
    )
    for record in records:
        if (
            record.is_project or not projects_only
        ) and record.project_name == canonical_project:
            return record
    raise _ProjectLifecycleNotFoundError(f"project '{project}' was not found")


def list_projects_for_state_filter(state_filter: str) -> list[ProjectRecordWire]:
    """Return project records matching *state_filter*, excluding the home node."""
    try:
        states = normalize_project_lifecycle_state_filter(state_filter)
    except ValueError as exc:
        raise ValueError(f"invalid project state: {state_filter}") from exc

    records = list_project_records(
        sase_projects_dir(),
        states,
        include_home=False,
    )
    return [record for record in records if record.is_project]


def list_aliased_project_records() -> list[ProjectRecordWire]:
    """Return every user-owned project record that carries at least one alias."""
    records = list_project_records(
        sase_projects_dir(),
        list(_ALL_STATES),
        include_home=False,
    )
    return [
        record
        for record in records
        if record.is_project and not record.system_managed and record.aliases
    ]


def _resolve_mutable_project_file(
    project: str,
    projects_root: Path | None = None,
) -> Path:
    root = (
        projects_root.expanduser() if projects_root is not None else sase_projects_dir()
    )
    project = _canonical_project_ref(project, root)
    if project == "home":
        raise _ProjectLifecycleError("project 'home' is system-managed")
    if not is_valid_sase_project_name(project):
        raise _ProjectLifecycleError(f"invalid project name: {project!r}")
    project_dir = root / project
    project_file = Path(preferred_project_spec_path(str(project_dir), project))
    if not project_file.is_file():
        raise _ProjectLifecycleNotFoundError(f"project '{project}' was not found")
    return project_file


def _resolve_deletable_project_dir(project: str, projects_root: Path) -> Path:
    project = _canonical_project_ref(project, projects_root)
    if project == "home":
        raise _ProjectLifecycleError("project 'home' is system-managed")
    if not is_valid_sase_project_name(project):
        raise _ProjectLifecycleError(f"invalid project name: {project!r}")

    root = projects_root.expanduser()
    root_resolved = root.resolve(strict=False)
    project_dir = root / project
    if project_dir.parent.resolve(strict=False) != root_resolved:
        raise _ProjectLifecycleError(
            f"project '{project}' is not a direct child of {root_resolved}"
        )
    if project_dir.is_symlink():
        raise _ProjectLifecycleError(
            f"project '{project}' is not an actual project directory"
        )
    if not project_dir.is_dir():
        raise _ProjectLifecycleNotFoundError(f"project '{project}' was not found")
    if project_dir.resolve(strict=True).parent != root_resolved:
        raise _ProjectLifecycleError(
            f"project '{project}' is not a direct child of {root_resolved}"
        )
    return project_dir


def _reject_system_managed_project(project: str, projects_root: Path) -> None:
    project = _canonical_project_ref(project, projects_root)
    if project == "home":
        raise _ProjectLifecycleError("project 'home' is system-managed")

    records = list_project_records(
        projects_root,
        list(_ALL_STATES),
        include_home=True,
    )
    for record in records:
        if record.project_name == project and record.system_managed:
            raise _ProjectLifecycleError(f"project '{project}' is system-managed")


def _live_artifact_marker_paths(project_dir: Path) -> list[Path]:
    artifacts_dir = project_dir / "artifacts"
    if not artifacts_dir.is_dir():
        return []

    markers: list[Path] = []
    for marker_name in _LIVE_ARTIFACT_MARKERS:
        markers.extend(
            path for path in artifacts_dir.rglob(marker_name) if path.is_file()
        )
    return sorted(markers)


def set_project_state_locked(
    project: str,
    state: str,
    *,
    force: bool = False,
) -> ProjectRecordWire:
    """Set lifecycle state for *project* while holding the ProjectSpec lock."""
    try:
        state = normalize_project_lifecycle_state(state)
    except ValueError as exc:
        raise _ProjectLifecycleError(f"invalid project state: {state}") from exc

    project = _canonical_project_ref(project)
    project_file = _resolve_mutable_project_file(project)
    with patch_lock(str(project_file)):
        content = project_file.read_text(encoding="utf-8")
        claims = list_workspace_claims_from_content(content)
        markers = _live_artifact_marker_paths(project_file.parent)
        if (
            is_disabled_project_lifecycle_state(state)
            and not force
            and (claims or markers)
        ):
            raise _ProjectLifecycleBlockedError(project, state, claims, markers)

        updated = apply_project_lifecycle_update(content, state)
        write_patch_atomic(
            str(project_file),
            updated,
            f"Set PROJECT_STATE to {state}",
        )

    _invalidate_project_identity()
    return get_project_record(project, projects_only=False)


def delete_project_locked(
    project: str,
    *,
    projects_root: Path | None = None,
) -> Path:
    """Delete a SASE project state directory while holding the ProjectSpec lock."""
    root = (
        projects_root.expanduser() if projects_root is not None else sase_projects_dir()
    )
    project = _canonical_project_ref(project, root)
    project_dir = _resolve_deletable_project_dir(project, root)
    _reject_system_managed_project(project, root)
    project_file = Path(preferred_project_spec_path(str(project_dir), project))

    with patch_lock(str(project_file)):
        project_dir = _resolve_deletable_project_dir(project, root)
        _reject_system_managed_project(project, root)
        project_file = Path(preferred_project_spec_path(str(project_dir), project))
        markers = _live_artifact_marker_paths(project_dir)
        claims: list[WorkspaceClaim] = []
        if project_file.is_file():
            content = project_file.read_text(encoding="utf-8")
            claims = list_workspace_claims_from_content(content)
        if claims or markers:
            raise _ProjectLifecycleBlockedError(project, "delete", claims, markers)

        shutil.rmtree(project_dir)

    _invalidate_project_identity(root)
    return project_dir
