"""Generic primary-sidecar auto-sync: opt-in conservative convergence.

One role-agnostic synchronizer for every configured sidecar (plans, beads,
research, and arbitrary custom roles) that opts into ``auto_sync``. It only
fetches and fast-forwards a materialized clone that is clean, attached, and
strictly behind its configured remote; dirty, detached, diverged, mismatched,
missing, or busy clones are left untouched and reported. It never mutates the
primary repository itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import subprocess
from typing import Any, Literal

from sase._git_remote import git_remotes_match
from sase._linked_repo_config import (
    HIDDEN_SIDECAR_ROLES,
    _SIDECAR_REMOTE_URL_KEY,
    _SIDECAR_REPO_MARKER,
    _SIDECAR_ROLE_KEY,
    inject_default_linked_repos,
    merged_repo_entries_from_config,
    read_project_local_config,
    resolution_config,
)
from sase._linked_repo_workspaces import refresh_clean_linked_checkout
from sase.version._git import classify_git_upstream
from sase.workspace_provider.ownership import (
    WorkspaceOwnershipError,
    primary_sidecar_sync_context,
    writable_sidecar_root,
)

SidecarSyncStatus = Literal[
    "refreshed",
    "up_to_date",
    "missing",
    "dirty",
    "detached",
    "no_upstream",
    "diverged",
    "remote_mismatch",
    "not_configured",
    "error",
]

#: Statuses that reflect a materialized clone SASE deliberately left alone.
SKIPPED_SYNC_STATUSES: frozenset[SidecarSyncStatus] = frozenset(
    {
        "dirty",
        "detached",
        "no_upstream",
        "diverged",
        "remote_mismatch",
        "error",
    }
)


@dataclass(frozen=True)
class SidecarSyncResult:
    """Outcome of one role's auto-sync attempt for one project."""

    project: str
    role: str
    status: SidecarSyncStatus
    detail: str

    @property
    def refreshed(self) -> bool:
        return self.status == "refreshed"

    @property
    def skipped(self) -> bool:
        return self.status in SKIPPED_SYNC_STATUSES


def _resolved_sidecar_entries(
    primary_workspace_dir: str,
    *,
    config: Mapping[str, Any] | None = None,
) -> list[Mapping[str, Any]]:
    """Return every configured sidecar entry for *primary_workspace_dir*.

    Combines explicit ``repos.sidecar`` declarations with implicit
    managed-project defaults, matching what ``sase repo inventory`` resolves.
    """

    resolved_config = resolution_config(primary_workspace_dir, config)
    local_config = read_project_local_config(primary_workspace_dir)
    entries, _ = merged_repo_entries_from_config(
        resolved_config,
        primary_workspace_dir=primary_workspace_dir,
    )
    entries = inject_default_linked_repos(
        entries,
        primary_workspace_dir=primary_workspace_dir,
        local_config=local_config,
        config=resolved_config,
    )
    return [entry for entry in entries if entry.get(_SIDECAR_REPO_MARKER) is True]


def auto_sync_roles(
    primary_workspace_dir: str,
    *,
    config: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    """Return configured sidecar roles opted into auto-sync, in declared order."""

    roles: list[str] = []
    for entry in _resolved_sidecar_entries(primary_workspace_dir, config=config):
        if entry.get("disabled") is True or entry.get("auto_sync") is not True:
            continue
        role = entry.get(_SIDECAR_ROLE_KEY)
        if not isinstance(role, str) or not role or role in HIDDEN_SIDECAR_ROLES:
            continue
        roles.append(role)
    return tuple(dict.fromkeys(roles))


def sync_primary_sidecar_role(
    project: str,
    role: str,
    *,
    project_file: str | Path | None = None,
    config: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> SidecarSyncResult:
    """Fetch and fast-forward one opted-in primary sidecar clone, if safe."""

    try:
        context = primary_sidecar_sync_context(
            project,
            role,
            project_file=project_file,
            config=config,
            env=env,
        )
    except WorkspaceOwnershipError as exc:
        return SidecarSyncResult(project, role, "error", str(exc))

    primary = str(context.primary_checkout_dir)
    entries = _resolved_sidecar_entries(primary, config=config)
    entry = next(
        (
            candidate
            for candidate in entries
            if candidate.get(_SIDECAR_ROLE_KEY) == role
        ),
        None,
    )
    if (
        entry is None
        or entry.get("disabled") is True
        or entry.get("auto_sync") is not True
    ):
        return SidecarSyncResult(
            project,
            role,
            "not_configured",
            f"sidecar role {role!r} is not configured for auto_sync",
        )

    try:
        clone_dir = Path(writable_sidecar_root(context, role))
    except WorkspaceOwnershipError as exc:
        return SidecarSyncResult(project, role, "error", str(exc))

    if not clone_dir.is_dir():
        return SidecarSyncResult(
            project, role, "missing", f"sidecar clone not materialized at {clone_dir}"
        )

    expected_remote = entry.get(_SIDECAR_REMOTE_URL_KEY)
    if isinstance(expected_remote, str) and expected_remote.strip():
        origin = _git_origin_url(clone_dir)
        if origin is None or not git_remotes_match(origin, expected_remote):
            return SidecarSyncResult(
                project,
                role,
                "remote_mismatch",
                f"clone origin {origin!r} does not match configured remote "
                f"{expected_remote!r}",
            )

    # Only fetch-independent facts (dirty/detached/no-upstream) are safe to
    # gate on before fetching: the local tracking ref reflects the state as
    # of the last fetch, so ahead/behind/up-to-date can only be trusted once
    # ``refresh_clean_linked_checkout`` has fetched from the remote below.
    try:
        pre_fetch_status = classify_git_upstream(clone_dir)
    except (
        FileNotFoundError,
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        return SidecarSyncResult(project, role, "error", str(exc))

    if pre_fetch_status.dirty:
        return SidecarSyncResult(
            project, role, "dirty", "sidecar clone has local changes"
        )
    if pre_fetch_status.detached:
        return SidecarSyncResult(
            project, role, "detached", "sidecar clone HEAD is detached"
        )
    if not pre_fetch_status.has_upstream:
        return SidecarSyncResult(
            project, role, "no_upstream", "sidecar clone branch has no upstream"
        )

    try:
        refreshed = refresh_clean_linked_checkout(str(clone_dir))
    except Exception as exc:  # noqa: BLE001 - best-effort convergence; never raise.
        return SidecarSyncResult(project, role, "error", str(exc))
    if refreshed is not None:
        return SidecarSyncResult(project, role, "refreshed", refreshed)

    # Nothing changed. Reclassify post-fetch to explain why, for diagnostics.
    try:
        status = classify_git_upstream(clone_dir)
    except (
        FileNotFoundError,
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        return SidecarSyncResult(project, role, "error", str(exc))

    if status.dirty:
        return SidecarSyncResult(
            project, role, "dirty", "sidecar clone has local changes"
        )
    if status.detached:
        return SidecarSyncResult(
            project, role, "detached", "sidecar clone HEAD is detached"
        )
    if not status.has_upstream:
        return SidecarSyncResult(
            project, role, "no_upstream", "sidecar clone branch has no upstream"
        )
    if status.diverged:
        return SidecarSyncResult(
            project,
            role,
            "diverged",
            f"{status.ahead} ahead / {status.behind} behind {status.upstream}",
        )
    if status.up_to_date:
        return SidecarSyncResult(
            project, role, "up_to_date", f"already at {status.upstream}"
        )
    return SidecarSyncResult(
        project, role, "error", "fetch/merge did not converge the sidecar clone"
    )


def _git_origin_url(path: Path) -> str | None:
    # Origin/status inspection is read-only; only the fetch/merge above mutates Git.
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=path,
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


__all__ = [
    "SKIPPED_SYNC_STATUSES",
    "SidecarSyncResult",
    "SidecarSyncStatus",
    "auto_sync_roles",
    "sync_primary_sidecar_role",
]
