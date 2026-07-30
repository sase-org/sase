"""Resolve enabled project sync targets through lifecycle and repo inventory."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from sase.agents_sync.models import ProjectTarget, SyncOutcome, TargetSelection
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    effective_project_name,
    is_disabled_project_lifecycle_state,
)
from sase.repo_inventory import (
    RepoInventory,
    RepoInventoryProjectNotFoundError,
    collect_repo_inventory,
    repo_display_name,
)


def resolve_sync_targets(
    projects: Sequence[str] = (),
    *,
    projects_root: Path | str | None = None,
) -> TargetSelection:
    """Pair primary/agents inventory rows for selected enabled projects."""

    root = Path(projects_root) if projects_root is not None else sase_projects_dir()
    lifecycle = list_project_records(
        root,
        "all",
        include_home=False,
        projects_only=True,
    )
    by_key = {record.project_name: record for record in lifecycle}

    inventories: list[RepoInventory] = []
    early_outcomes: list[SyncOutcome] = []
    if projects:
        for selector in dict.fromkeys(project.strip() for project in projects):
            if not selector:
                early_outcomes.append(
                    SyncOutcome("", "", error="project selectors cannot be empty")
                )
                continue
            record = _matching_record(lifecycle, selector)
            if record is not None and is_disabled_project_lifecycle_state(record.state):
                early_outcomes.append(
                    SyncOutcome(
                        record.project_name,
                        effective_project_name(record),
                        skip_reason="project is disabled",
                    )
                )
                continue
            try:
                inventories.append(collect_repo_inventory(root, project=selector))
            except RepoInventoryProjectNotFoundError as exc:
                early_outcomes.append(SyncOutcome(selector, selector, error=str(exc)))
            except Exception as exc:  # noqa: BLE001 - isolated selection outcome
                early_outcomes.append(
                    SyncOutcome(
                        selector,
                        selector,
                        error=f"could not collect repository inventory: {exc}",
                    )
                )
    else:
        try:
            inventories.append(collect_repo_inventory(root))
        except Exception as exc:  # noqa: BLE001 - structured global outcome
            return TargetSelection(
                outcomes=(
                    SyncOutcome(
                        "*",
                        "all projects",
                        error=f"could not collect repository inventory: {exc}",
                    ),
                )
            )

    targets: dict[str, ProjectTarget] = {}
    outcomes: dict[str, SyncOutcome] = {
        outcome.project_key: outcome for outcome in early_outcomes
    }
    for inventory in inventories:
        project_keys = {
            record.project_key
            for record in inventory.records
            if record.kind == "primary"
        }
        for project_key in sorted(project_keys):
            if project_key in targets or project_key in outcomes:
                continue
            records = [
                record
                for record in inventory.records
                if record.project_key == project_key
            ]
            primary = next(
                (record for record in records if record.kind == "primary"), None
            )
            agents = next(
                (
                    record
                    for record in records
                    if record.kind == "sidecar" and record.name == "agents"
                ),
                None,
            )
            lifecycle_record = by_key.get(project_key)
            project = (
                effective_project_name(lifecycle_record)
                if lifecycle_record is not None
                else primary.project
                if primary is not None
                else project_key
            )
            issues = [
                issue.message
                for issue in inventory.issues
                if issue.project == project
                or (primary is not None and issue.project == primary.project)
            ]
            if primary is None or not primary.path:
                outcomes[project_key] = SyncOutcome(
                    project_key,
                    project,
                    error="project has no primary checkout metadata",
                    diagnostics=tuple(issues),
                )
                continue
            if agents is None:
                outcomes[project_key] = SyncOutcome(
                    project_key,
                    project,
                    skip_reason="agents sidecar is disabled or unavailable",
                    diagnostics=tuple(issues),
                )
                continue
            if not agents.path:
                outcomes[project_key] = SyncOutcome(
                    project_key,
                    project,
                    error="agents sidecar has no machine-level clone path",
                    diagnostics=tuple(issues),
                )
                continue
            if not agents.remote_url:
                outcomes[project_key] = SyncOutcome(
                    project_key,
                    project,
                    skip_reason="agents sidecar has not been created",
                    diagnostics=tuple(issues),
                )
                continue

            primary_paths = [Path(primary.path).expanduser()]
            primary_paths.extend(
                Path(clone.path).expanduser()
                for clone in primary.clones
                if clone.exists and clone.path
            )
            resolved_roots = tuple(
                dict.fromkeys(path.resolve(strict=False) for path in primary_paths)
            )
            targets[project_key] = ProjectTarget(
                project_key=project_key,
                project=project,
                primary_checkout=Path(primary.path).expanduser(),
                primary_roots=resolved_roots,
                sidecar_path=Path(agents.path).expanduser(),
                remote_url=agents.remote_url,
                primary_repo_name=repo_display_name(primary),
            )

        for issue in inventory.issues:
            if issue.project in {target.project for target in targets.values()}:
                continue
            matching = next(
                (
                    record
                    for record in inventory.records
                    if record.project == issue.project and record.kind == "primary"
                ),
                None,
            )
            if matching is None:
                continue
            outcomes.setdefault(
                matching.project_key,
                SyncOutcome(
                    matching.project_key,
                    matching.project,
                    error=f"repository inventory error: {issue.message}",
                ),
            )

    return TargetSelection(
        targets=tuple(sorted(targets.values(), key=lambda item: item.project_key)),
        outcomes=tuple(sorted(outcomes.values(), key=lambda item: item.project_key)),
    )


def _matching_record(
    records: Sequence[ProjectRecordWire], selector: str
) -> ProjectRecordWire | None:
    return next(
        (
            record
            for record in records
            if selector
            in {
                record.project_name,
                effective_project_name(record),
                *record.aliases,
            }
        ),
        None,
    )


__all__ = ["resolve_sync_targets"]
