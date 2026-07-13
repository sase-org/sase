"""Frontend-neutral inventory of registered SASE workspaces.

This module is intentionally a thin Python domain adapter. Project and claim
parsing are Rust-owned, while workspace registries and store configuration are
still Python-owned. If those inputs move into ``sase-core``, this adapter is the
migration seam; CLI and TUI consumers should keep using this inventory API.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
import time
from typing import Any

from sase._linked_repo_config import resolution_config
from sase.core.agent_launch_claims import list_workspace_claims_from_content
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    effective_project_name,
)
from sase.running_field._model import WorkspaceClaim
from sase.workspace_provider.registry import (
    WorkspaceEntry,
    WorkspaceRegistryError,
    load_registry,
    registry_path,
)
from sase.workspace_provider.store import PRIMARY_WORKSPACE_NUM, WorkspaceStore

ProcessRunningProbe = Callable[[int], bool]


@dataclass(frozen=True)
class WorkspaceProjectInfo:
    """Store metadata for one project represented in the inventory."""

    project: str
    project_key: str
    state: str
    root_policy: str
    root_dir: str
    primary_workspace_dir: str
    registry_path: str
    cleanup_ttl_days: int

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class WorkspaceInventoryRecord:
    """One registry workspace joined with its optional RUNNING claim."""

    workspace_num: int
    project: str
    project_key: str
    project_state: str
    checkout_dir: str
    exists: bool
    materialization: str
    role: str
    pinned: bool
    created_at: float
    last_used_at: float
    generation: int
    stale: bool
    cleanup_ttl_days: int
    registry_path: str
    claim_agent: str | None = None
    claim_pid: int | None = None
    claim_pid_alive: bool | None = None
    claim_cl_name: str | None = None
    claim_timestamp: str | None = None
    claim_pinned: bool = False

    @property
    def claimed(self) -> bool:
        return self.claim_agent is not None

    def to_json_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["claimed"] = self.claimed
        return payload


@dataclass(frozen=True)
class WorkspaceInventoryIssue:
    """A non-fatal problem isolated to one project."""

    project: str
    message: str

    def to_json_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class WorkspaceInventory:
    """Workspace records, project store metadata, and isolated issues."""

    records: tuple[WorkspaceInventoryRecord, ...]
    projects: tuple[WorkspaceProjectInfo, ...]
    issues: tuple[WorkspaceInventoryIssue, ...] = ()

    def to_json_dict(self) -> dict[str, object]:
        return {
            "projects": [project.to_json_dict() for project in self.projects],
            "workspaces": [record.to_json_dict() for record in self.records],
            "issues": [issue.to_json_dict() for issue in self.issues],
        }


class WorkspaceInventoryProjectNotFoundError(ValueError):
    """Raised when an explicit project filter matches no inventory host."""


def collect_workspace_inventory(
    projects_root: Path | str | None = None,
    *,
    project: str | None = None,
    include_disabled: bool = False,
    now: float | None = None,
    process_running: ProcessRunningProbe | None = None,
) -> WorkspaceInventory:
    """Collect registered workspaces across projects.

    The default view contains enabled true projects. An explicit project is
    looked up across enabled and disabled projects; sibling backing records
    remain accepted only for compatibility with direct linked-repo CLI queries.
    Callers implementing an all-projects view can opt into disabled projects
    with *include_disabled*. A corrupt registry or ProjectSpec becomes an issue
    for that project while records from every other project remain available.
    """

    root = Path(projects_root) if projects_root is not None else sase_projects_dir()
    include_states: Sequence[str] | str = (
        "all" if project is not None or include_disabled else "enabled"
    )
    discovered = list_project_records(
        root,
        include_states,
        include_home=False,
        projects_only=False,
    )
    if project is not None:
        projects = [
            record
            for record in discovered
            if (record.is_project or record.state == "sibling")
            and _record_matches_project(record, project)
        ]
        if not projects:
            raise WorkspaceInventoryProjectNotFoundError(
                f"project '{project}' was not found"
            )
    else:
        projects = [record for record in discovered if record.is_project]

    current_time = time.time() if now is None else now
    process_probe = process_running or _default_process_running
    records: list[WorkspaceInventoryRecord] = []
    project_infos: list[WorkspaceProjectInfo] = []
    issues: list[WorkspaceInventoryIssue] = []

    for project_record in projects:
        project_records, project_info, project_issues = _collect_project_workspaces(
            project_record,
            now=current_time,
            process_running=process_probe,
        )
        records.extend(project_records)
        if project_info is not None:
            project_infos.append(project_info)
        issues.extend(project_issues)

    records.sort(
        key=lambda record: (
            record.project.casefold(),
            record.workspace_num,
            record.checkout_dir,
        )
    )
    project_infos.sort(key=lambda info: info.project.casefold())
    return WorkspaceInventory(
        records=tuple(records),
        projects=tuple(project_infos),
        issues=tuple(issues),
    )


def _collect_project_workspaces(
    project_record: ProjectRecordWire,
    *,
    now: float,
    process_running: ProcessRunningProbe,
) -> tuple[
    list[WorkspaceInventoryRecord],
    WorkspaceProjectInfo | None,
    list[WorkspaceInventoryIssue],
]:
    project = effective_project_name(project_record)
    raw_primary = (project_record.workspace_dir or "").strip()
    if not raw_primary:
        return (
            [],
            None,
            [
                WorkspaceInventoryIssue(
                    project,
                    f"{project_record.project_file} has no WORKSPACE_DIR",
                )
            ],
        )

    primary = str(Path(raw_primary).expanduser().resolve(strict=False))
    try:
        config = resolution_config(primary, None)
        store = WorkspaceStore(primary, config=config)
    except Exception as exc:
        return (
            [],
            None,
            [
                WorkspaceInventoryIssue(
                    project,
                    f"Unable to resolve workspace store: {exc}",
                )
            ],
        )

    registry_file = registry_path(store.root_dir)
    project_info = WorkspaceProjectInfo(
        project=project,
        project_key=project_record.project_name,
        state=project_record.state,
        root_policy=store.root_policy,
        root_dir=store.root_dir,
        primary_workspace_dir=store.primary_workspace_dir,
        registry_path=registry_file,
        cleanup_ttl_days=store.cleanup_ttl_days,
    )
    try:
        registry = load_registry(store, strict=True)
    except WorkspaceRegistryError as exc:
        return [], project_info, [WorkspaceInventoryIssue(project, str(exc))]

    issues: list[WorkspaceInventoryIssue] = []
    claims = _read_claims(project_record, project=project, issues=issues)
    claims_by_num: dict[int, WorkspaceClaim] = {}
    for claim in claims:
        # Workspace #0 is a deferred-allocation placeholder, not an ownership
        # claim on the primary checkout. Multiple launches may legitimately
        # carry it while they wait for a numbered workspace.
        if claim.workspace_num == PRIMARY_WORKSPACE_NUM:
            continue
        if claim.workspace_num in claims_by_num:
            issues.append(
                WorkspaceInventoryIssue(
                    project,
                    f"Multiple RUNNING claims reference workspace #{claim.workspace_num}",
                )
            )
            continue
        claims_by_num[claim.workspace_num] = claim

    rows: list[WorkspaceInventoryRecord] = []
    registered_nums: set[int] = set()
    for raw_num, entry in registry.workspaces.items():
        try:
            workspace_num = int(raw_num)
        except (TypeError, ValueError):
            issues.append(
                WorkspaceInventoryIssue(
                    project,
                    f"Ignoring non-numeric registry workspace key {raw_num!r}",
                )
            )
            continue

        registered_nums.add(workspace_num)
        joined_claim = claims_by_num.get(workspace_num)
        checkout_dir = entry.checkout_dir.rstrip("/") or entry.checkout_dir
        claim_alive = _claim_liveness(
            joined_claim,
            process_running=process_running,
            project=project,
            issues=issues,
        )
        pinned = entry.pinned or bool(joined_claim is not None and joined_claim.pinned)
        stale = (
            workspace_num != PRIMARY_WORKSPACE_NUM
            and joined_claim is None
            and not pinned
            and (now - entry.last_used_at) > float(store.cleanup_ttl_days) * 86400.0
        )
        rows.append(
            _workspace_record(
                project_record,
                project=project,
                workspace_num=workspace_num,
                entry=entry,
                checkout_dir=checkout_dir,
                exists=Path(checkout_dir).is_dir(),
                pinned=pinned,
                stale=stale,
                registry_file=registry_file,
                ttl_days=store.cleanup_ttl_days,
                claim=joined_claim,
                claim_alive=claim_alive,
            )
        )

    for workspace_num in sorted(set(claims_by_num) - registered_nums):
        issues.append(
            WorkspaceInventoryIssue(
                project,
                f"RUNNING claim #{workspace_num} has no workspace registry entry",
            )
        )

    rows.sort(key=lambda record: record.workspace_num)
    return rows, project_info, issues


def _read_claims(
    project_record: ProjectRecordWire,
    *,
    project: str,
    issues: list[WorkspaceInventoryIssue],
) -> list[WorkspaceClaim]:
    try:
        content = Path(project_record.project_file).read_text(encoding="utf-8")
        return list_workspace_claims_from_content(content)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        issues.append(
            WorkspaceInventoryIssue(project, f"Unable to read RUNNING claims: {exc}")
        )
        return []


def _claim_liveness(
    claim: WorkspaceClaim | None,
    *,
    process_running: ProcessRunningProbe,
    project: str,
    issues: list[WorkspaceInventoryIssue],
) -> bool | None:
    if claim is None:
        return None
    try:
        return process_running(claim.pid)
    except (OSError, RuntimeError, ValueError) as exc:
        issues.append(
            WorkspaceInventoryIssue(
                project,
                f"Unable to probe claim PID {claim.pid}: {exc}",
            )
        )
        return False


def _workspace_record(
    project_record: ProjectRecordWire,
    *,
    project: str,
    workspace_num: int,
    entry: WorkspaceEntry,
    checkout_dir: str,
    exists: bool,
    pinned: bool,
    stale: bool,
    registry_file: str,
    ttl_days: int,
    claim: WorkspaceClaim | None,
    claim_alive: bool | None,
) -> WorkspaceInventoryRecord:
    return WorkspaceInventoryRecord(
        workspace_num=workspace_num,
        project=project,
        project_key=project_record.project_name,
        project_state=project_record.state,
        checkout_dir=checkout_dir,
        exists=exists,
        materialization=entry.materialization,
        role=entry.role,
        pinned=pinned,
        created_at=entry.created_at,
        last_used_at=entry.last_used_at,
        generation=entry.generation,
        stale=stale,
        cleanup_ttl_days=ttl_days,
        registry_path=registry_file,
        claim_agent=claim.workflow if claim is not None else None,
        claim_pid=claim.pid if claim is not None else None,
        claim_pid_alive=claim_alive,
        claim_cl_name=claim.cl_name if claim is not None else None,
        claim_timestamp=claim.artifacts_timestamp if claim is not None else None,
        claim_pinned=claim.pinned if claim is not None else False,
    )


def _record_matches_project(record: ProjectRecordWire, project: str) -> bool:
    candidate = project.strip()
    return candidate in {
        record.project_name,
        effective_project_name(record),
        *record.aliases,
    }


def _default_process_running(pid: int) -> bool:
    from sase.ace.hooks.processes import is_process_running

    return is_process_running(pid)


__all__ = [
    "ProcessRunningProbe",
    "WorkspaceInventory",
    "WorkspaceInventoryIssue",
    "WorkspaceInventoryProjectNotFoundError",
    "WorkspaceInventoryRecord",
    "WorkspaceProjectInfo",
    "collect_workspace_inventory",
]
