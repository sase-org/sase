"""Machine-writable bead stores for runner and scheduled writers.

Background bead mutations must not resolve
:func:`~sase.bead.store_locator.canonical_beads_dir_for_project`. That
locator is the user-owned primary snapshot. Writers acquire a short
operational lease — or reuse the current claimed workspace when its
beads store is a separate workspace-local sidecar — and schedule
primary-sidecar convergence after publication instead of pulling the
primary clone.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.workspace_provider.ownership import (
    MACHINE_OWNED_MIN_WORKSPACE,
    OperationContext,
    WorkspaceOwnershipError,
    leased_operational_context,
    normalize_workspace_num,
    writable_beads_dir,
)


@dataclass(frozen=True)
class WritableBeadStore:
    """One machine-writable bead store plus the context that owns it."""

    project: str
    beads_dir: Path
    context: OperationContext
    reused_existing_claim: bool


def schedule_beads_sidecar_convergence(project: str) -> None:
    """Record that *project*'s beads role should converge on the primary sidecar.

    Hints live in SASE state, not in a repository checkout, so this never
    touches the primary clone. The auto-sync worker consumes the hint.
    """

    if not project or project == "home":
        return
    try:
        from sase._sidecar_sync_hints import mark_sidecar_sync_hint

        mark_sidecar_sync_hint(project, "beads")
    except Exception:
        return


@contextmanager
def writable_bead_store_for_machine(
    project: str,
    *,
    workflow: str,
    holder: str,
    prefer_existing_claim: bool = False,
    project_file: str | Path | None = None,
    config: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> Iterator[WritableBeadStore]:
    """Yield a writable workspace-local bead store for SASE-initiated work.

    When *prefer_existing_claim* is true, a live numbered workspace is
    reused only if its beads store is a separate workspace-local sidecar
    so a later reset cannot discard the caller's code edits. Otherwise a
    short operational lease is acquired. The primary checkout is never
    used as a fallback.
    """

    if not project or project == "home":
        raise RuntimeError(f"no writable bead store for project {project!r}")

    if prefer_existing_claim:
        reused = _try_reuse_existing_claimed_sidecar(
            project,
            project_file=project_file,
            config=config,
            env=env,
        )
        if reused is not None:
            yield reused
            return

    from sase.workspace_provider.lease import operational_workspace_lease

    with operational_workspace_lease(
        project,
        workflow=workflow,
        holder=holder,
        project_file=project_file,
        config=config,
        env=env,
    ) as lease:
        yield WritableBeadStore(
            project=project,
            beads_dir=_materialize_writable_beads(lease.context),
            context=lease.context,
            reused_existing_claim=False,
        )


def _try_reuse_existing_claimed_sidecar(
    project: str,
    *,
    project_file: str | Path | None,
    config: Mapping[str, Any] | None,
    env: Mapping[str, str] | None,
) -> WritableBeadStore | None:
    """Reuse the current claimed workspace when beads are a separate sidecar."""

    try:
        from sase.workspace_provider.marker import find_marker_from_cwd

        found = find_marker_from_cwd(os.getcwd())
    except Exception:
        return None
    if found is None:
        return None
    checkout, marker = found
    workspace_num = normalize_workspace_num(marker.workspace_num)
    if workspace_num < MACHINE_OWNED_MIN_WORKSPACE:
        return None
    try:
        context = leased_operational_context(
            project,
            workspace_num,
            checkout_dir=checkout,
            project_file=project_file,
            config=config,
            env=env,
        )
        beads_dir = _materialize_writable_beads(context)
    except (OSError, RuntimeError, WorkspaceOwnershipError):
        return None
    if not _is_separate_workspace_local_sidecar(context, beads_dir):
        return None
    return WritableBeadStore(
        project=project,
        beads_dir=beads_dir,
        context=context,
        reused_existing_claim=True,
    )


def _materialize_writable_beads(context: OperationContext) -> Path:
    """Resolve the writable beads root and materialize a sidecar clone if needed."""

    from sase.sdd.store import ensure_sdd_kind_clone

    try:
        ensure_sdd_kind_clone(
            context.checkout_dir,
            context.workspace_num,
            "beads",
            strict=False,
        )
    except Exception:
        pass
    beads_dir = writable_beads_dir(context)
    if not beads_dir.is_dir():
        raise RuntimeError(
            f"no writable bead store for project '{context.project}' "
            f"in workspace #{context.workspace_num}"
        )
    return beads_dir


def _is_separate_workspace_local_sidecar(
    context: OperationContext,
    beads_dir: Path,
) -> bool:
    """Return whether *beads_dir* is a distinct git repo inside *context*."""

    checkout = context.checkout_dir.resolve()
    beads = beads_dir.resolve()
    try:
        beads.relative_to(checkout)
    except ValueError:
        return False
    checkout_git = _git_root(checkout)
    beads_git = _git_root(beads)
    if checkout_git is None or beads_git is None or beads_git == checkout_git:
        return False
    try:
        beads_git.relative_to(checkout)
    except ValueError:
        return False
    return True


def _git_root(path: Path) -> Path | None:
    from sase.bead._sync_git import find_git_root

    return find_git_root(path)


__all__ = [
    "WritableBeadStore",
    "schedule_beads_sidecar_convergence",
    "writable_bead_store_for_machine",
]
