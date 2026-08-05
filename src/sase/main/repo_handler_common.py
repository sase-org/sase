"""Shared resolution helpers for ``sase repo`` commands."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from sase.repo_inventory import RepoCloneRecord, RepoInventory, RepoRecord
from sase.workspace_provider.marker import CheckoutMarker

from .workspace_handler_context import ProjectContext


InventoryCollector = Callable[..., RepoInventory]
MarkerFinder = Callable[[str], tuple[str, CheckoutMarker] | None]
ProjectContextResolver = Callable[[str | None], ProjectContext]


class RepoOpenResolutionError(ValueError):
    """Raised when a repository or workspace context cannot be resolved."""


def clone_for_workspace(record: RepoRecord, workspace_num: int) -> RepoCloneRecord:
    clone = record.clone_for_workspace(workspace_num)
    if clone is not None:
        return clone
    if workspace_num == 0:
        # Compatibility for callers constructing the pre-enrichment record
        # shape, including ACE fixtures and third-party consumers.
        return RepoCloneRecord(0, record.path, record.exists)
    raise RepoOpenResolutionError(
        f"workspace #{workspace_num} is not registered for project '{record.project}'"
    )


def resolve_list_workspace_num(
    host_ctx: ProjectContext,
    requested_workspace: int | None,
    *,
    find_marker: MarkerFinder,
    cwd: Path | None = None,
) -> int:
    if requested_workspace is not None:
        workspace_num = int(requested_workspace)
        if workspace_num < 0:
            raise RepoOpenResolutionError(
                f"workspace number must be >= 0, got {workspace_num}"
            )
        return workspace_num

    found = find_marker(str((cwd or Path.cwd()).resolve(strict=False)))
    if found is None:
        return 0
    _, marker = found
    marker_primary = Path(marker.primary_workspace_dir).resolve(strict=False)
    host_primary = Path(host_ctx.primary_workspace_dir).resolve(strict=False)
    if marker_primary != host_primary:
        return 0
    return marker.workspace_num if marker.workspace_num >= 0 else 0


def validate_workspace_context(
    records: Sequence[RepoRecord],
    *,
    project: str,
    workspace_num: int,
) -> None:
    if not records or workspace_num == 0:
        return
    registered = sorted(
        {clone.workspace_num for record in records for clone in record.clones}
    )
    if workspace_num in registered:
        return
    candidates = ", ".join(str(item) for item in registered) or "0"
    raise RepoOpenResolutionError(
        f"workspace #{workspace_num} is not registered for project '{project}'. "
        f"Registered workspaces: {candidates}"
    )


def match_repo_record(
    name: str,
    *,
    host_ctx: ProjectContext,
    inventory: RepoInventory,
) -> RepoRecord | None:
    """Return an exact tier-1 inventory match without guessing.

    Materialized external rows are intentionally excluded: they re-enter the
    external resolver so reopen semantics never run the linked-repo cleaner.
    """

    requested = name.strip()

    # An exact path (as printed by ambiguous_repo_error) always selects one
    # record, even when its name/slug collides with another record's.
    path_matches = [
        record
        for record in inventory.records
        if record.kind in {"primary", "sidecar", "linked"} and record.path == requested
    ]
    if len(path_matches) == 1:
        return path_matches[0]

    secondary_matches = [
        record
        for record in inventory.records
        if record.kind in {"sidecar", "linked"}
        and requested in {record.name, record.slug}
    ]
    if len(secondary_matches) == 1:
        return secondary_matches[0]
    if len(secondary_matches) > 1:
        raise ambiguous_repo_error(requested, secondary_matches)

    primary_matches = [
        record
        for record in inventory.records
        if record.kind == "primary"
        and requested in {record.name, host_ctx.project_name}
    ]
    if len(primary_matches) == 1:
        return primary_matches[0]
    if len(primary_matches) > 1:
        raise ambiguous_repo_error(requested, primary_matches)

    return None


def ambiguous_repo_error(
    requested: str,
    matches: list[RepoRecord],
) -> RepoOpenResolutionError:
    candidates = ", ".join(
        f"{record.kind} '{record.name}' ({record.path})" for record in matches
    )
    return RepoOpenResolutionError(
        f"Repo name '{requested}' is ambiguous: {candidates}. "
        "Pass one of the listed paths as the repo argument to select it."
    )


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
