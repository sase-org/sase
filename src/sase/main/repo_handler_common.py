"""Shared resolution helpers for ``sase repo`` commands."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
import subprocess

from sase.core.repository_resolution_facade import (
    canonical_repository_identity,
    resolve_repository_reference,
)
from sase.external_repos import (
    ExternalRepoRefError,
    external_repo_clone_parts_from_name,
)
from sase.linked_repos import external_repo_clone_dir
from sase.repo_inventory import RepoCloneRecord, RepoInventory, RepoRecord
from sase.workspace_provider._utils_git import non_interactive_git_env
from sase.workspace_provider.marker import CheckoutMarker

from .workspace_handler_context import ProjectContext


InventoryCollector = Callable[..., RepoInventory]
MarkerFinder = Callable[[str], tuple[str, CheckoutMarker] | None]
ProjectContextResolver = Callable[[str | None], ProjectContext]


class RepoOpenResolutionError(ValueError):
    """Raised when a repository or workspace context cannot be resolved."""


_CONFIGURED_REPO_KINDS = {"primary", "sidecar", "linked"}
_GIT_PROBE_TIMEOUT_SECONDS = 2.0


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
    workspace_num: int = 0,
) -> RepoRecord | None:
    """Return a configured inventory match without guessing.

    Materialized external rows are intentionally excluded: they re-enter the
    external resolver so reopen semantics never run the linked-repo cleaner.
    """

    requested = name.strip()
    configured = [
        record
        for record in inventory.records
        if record.project == host_ctx.project_name
        and record.kind in _CONFIGURED_REPO_KINDS
    ]

    records_by_id = {str(index): record for index, record in enumerate(configured)}
    exact_decision = resolve_repository_reference(
        {
            "requested": requested,
            "candidates": [
                _repo_resolution_candidate(
                    record,
                    record_id=str(index),
                    host_ctx=host_ctx,
                    workspace_num=workspace_num,
                    include_remotes=False,
                )
                for index, record in enumerate(configured)
            ],
        }
    )
    exact_match = _record_from_resolution(
        requested,
        exact_decision,
        records_by_id=records_by_id,
    )
    if exact_match is not None:
        return exact_match
    if exact_decision.get("requested_identity") is None:
        return None

    remote_decision = resolve_repository_reference(
        {
            "requested": requested,
            "candidates": [
                _repo_resolution_candidate(
                    record,
                    record_id=str(index),
                    host_ctx=host_ctx,
                    workspace_num=workspace_num,
                    include_remotes=True,
                )
                for index, record in enumerate(configured)
            ],
        }
    )
    remote_match = _record_from_resolution(
        requested,
        remote_decision,
        records_by_id=records_by_id,
    )
    if remote_match is not None:
        _ensure_no_external_collision(
            requested,
            remote_decision,
            configured_repo=remote_match,
            inventory=inventory,
            host_ctx=host_ctx,
            workspace_num=workspace_num,
        )
        return remote_match

    return None


def _record_from_resolution(
    requested: str,
    decision: dict[str, object],
    *,
    records_by_id: dict[str, RepoRecord],
) -> RepoRecord | None:
    status = decision.get("status")
    if status == "matched":
        matched_id = decision.get("matched_id")
        if isinstance(matched_id, str) and matched_id in records_by_id:
            return records_by_id[matched_id]
        raise RepoOpenResolutionError(
            f"Repo resolver returned unknown candidate id for '{requested}'"
        )
    if status == "ambiguous":
        candidate_ids = decision.get("candidate_ids")
        if not isinstance(candidate_ids, Sequence) or isinstance(
            candidate_ids, str | bytes | bytearray
        ):
            candidate_ids = []
        matches = [
            records_by_id[candidate_id]
            for candidate_id in candidate_ids
            if isinstance(candidate_id, str) and candidate_id in records_by_id
        ]
        raise ambiguous_repo_error(requested, matches)
    return None


def _repo_resolution_candidate(
    record: RepoRecord,
    *,
    record_id: str,
    host_ctx: ProjectContext,
    workspace_num: int,
    include_remotes: bool,
) -> dict[str, object]:
    aliases = []
    if record.slug:
        aliases.append(record.slug)
    if record.kind == "primary":
        aliases.append(host_ctx.project_name)

    return {
        "id": record_id,
        "name": record.name,
        "kind": record.kind,
        "path": record.path,
        "aliases": aliases,
        "remote_urls": (
            _record_remote_urls(record, workspace_num=workspace_num)
            if include_remotes
            else []
        ),
    }


def _record_remote_urls(
    record: RepoRecord,
    *,
    workspace_num: int,
) -> list[str]:
    urls: list[str] = []
    if record.remote_url:
        urls.append(record.remote_url)
        if record.kind == "sidecar":
            return _dedupe(urls)

    probe_path = _remote_probe_path(record, workspace_num)
    if probe_path is None:
        return _dedupe(urls)
    origin = _git_origin_url(probe_path)
    if origin:
        urls.append(origin)
    return _dedupe(urls)


def _remote_probe_path(record: RepoRecord, workspace_num: int) -> str | None:
    selected = record.clone_for_workspace(workspace_num)
    if selected is not None and selected.exists:
        return selected.path
    primary = record.clone_for_workspace(0)
    if primary is not None and primary.exists:
        return primary.path
    if Path(record.path).is_dir():
        return record.path
    return None


def _git_origin_url(path: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=path,
            capture_output=True,
            text=True,
            check=False,
            env=non_interactive_git_env(),
            stdin=subprocess.DEVNULL,
            timeout=_GIT_PROBE_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _ensure_no_external_collision(
    requested: str,
    decision: dict[str, object],
    *,
    configured_repo: RepoRecord,
    inventory: RepoInventory,
    host_ctx: ProjectContext,
    workspace_num: int,
) -> None:
    identity = decision.get("requested_identity")
    if not isinstance(identity, dict):
        identity = canonical_repository_identity(requested)
    if not isinstance(identity, dict):
        return
    canonical = identity.get("canonical")
    if not isinstance(canonical, str) or not canonical:
        return

    configured_path = _selected_repo_path(configured_repo, workspace_num)
    collision_paths = set(
        _matching_external_paths(
            canonical,
            inventory=inventory,
            workspace_num=workspace_num,
            configured_path=configured_path,
        )
    )
    standard = _standard_external_path(
        canonical,
        inventory=inventory,
        host_ctx=host_ctx,
        workspace_num=workspace_num,
    )
    if (
        standard is not None
        and _is_valid_git_repo(Path(standard))
        and not _same_path(standard, configured_path)
    ):
        collision_paths.add(standard)

    if not collision_paths:
        return
    collisions = ", ".join(sorted(collision_paths))
    raise RepoOpenResolutionError(
        f"Repo reference '{requested}' matches configured {configured_repo.kind} "
        f"repo '{configured_repo.name}' at {configured_path}, but an existing "
        f"external checkout for the same repository is already present at "
        f"{collisions}. Open '{configured_repo.name}' explicitly or recover the "
        "external checkout before using the provider alias."
    )


def _matching_external_paths(
    canonical: str,
    *,
    inventory: RepoInventory,
    workspace_num: int,
    configured_path: str,
) -> list[str]:
    paths: list[str] = []
    for record in inventory.records:
        if record.kind != "external":
            continue
        identity = canonical_repository_identity(record.name)
        if identity is None or identity.get("canonical") != canonical:
            continue
        clone = record.clone_for_workspace(workspace_num)
        path = clone.path if clone is not None else record.path
        exists = clone.exists if clone is not None else Path(path).is_dir()
        if exists and not _same_path(path, configured_path):
            paths.append(path)
    return paths


def _standard_external_path(
    canonical: str,
    *,
    inventory: RepoInventory,
    host_ctx: ProjectContext,
    workspace_num: int,
) -> str | None:
    try:
        clone_parts = external_repo_clone_parts_from_name(canonical)
    except (ExternalRepoRefError, ValueError):
        return None
    host_checkout = _host_checkout_path(
        inventory,
        host_ctx=host_ctx,
        workspace_num=workspace_num,
    )
    if host_checkout is None:
        return None
    return external_repo_clone_dir(host_checkout, clone_parts[0], *clone_parts[1:])


def _host_checkout_path(
    inventory: RepoInventory,
    *,
    host_ctx: ProjectContext,
    workspace_num: int,
) -> str | None:
    primary = next(
        (
            record
            for record in inventory.records
            if record.project == host_ctx.project_name and record.kind == "primary"
        ),
        None,
    )
    if primary is not None:
        clone = primary.clone_for_workspace(workspace_num)
        if clone is not None:
            return clone.path
        if workspace_num == 0:
            return primary.path
    if workspace_num == 0:
        return host_ctx.primary_workspace_dir
    return None


def _selected_repo_path(record: RepoRecord, workspace_num: int) -> str:
    clone = record.clone_for_workspace(workspace_num)
    return clone.path if clone is not None else record.path


def _is_valid_git_repo(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=path,
            capture_output=True,
            text=True,
            check=False,
            env=non_interactive_git_env(),
            stdin=subprocess.DEVNULL,
            timeout=_GIT_PROBE_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def _same_path(left: str, right: str) -> bool:
    return Path(left).expanduser().resolve(strict=False) == Path(
        right
    ).expanduser().resolve(strict=False)


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


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
