"""Machine-context artifact-link store resolution for host background work.

Background link maintenance (the hourly ``artifact_link_backfill`` chop and
the agents-sync Referenced By drain) must never write into a primary
checkout's nested sidecar clones -- see the ``hidden-clone-machine-writes``
phase this implements. This resolver maps every document sidecar role
(``plans`` plus any custom role such as ``research``) onto its project's
hidden host-owned clone (:func:`hidden_sidecar_clone_dir`), following the
existing ``agents`` sidecar precedent, and freshly integrates each clone from
its recorded remote before returning the store. Beads and the
already-hidden ``agents`` sidecar are left at their existing roots as read
context; only document roots move to the machine lane. Non-split storage has
no hidden lane and retains the existing resolved store, so the ownership
gate continues to fail closed there.

The primary checkout's own nested sidecar clones (``<primary>/sase/repos/*``)
are never touched by this module. They stay human-owned and converge with
the hidden clones this module writes only through the existing pull-based
``sync_primary_sidecar_role`` auto-sync.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from sase.sdd._artifact_link_store_impl import ArtifactLinkStore
from sase.sdd._store_types import SddStore, document_sidecar_roles
from sase.workspace_provider.store import PRIMARY_WORKSPACE_NUM


def resolve_machine_artifact_link_store(
    project_key: str,
    primary_checkout: str | Path,
) -> ArtifactLinkStore:
    """Resolve the machine-writable artifact-link store for *project_key*.

    Document sidecar roots resolve to their hidden host-owned clone under
    ``~/.sase/projects/<project_key>/repos/<role>``, materialized or freshly
    integrated from the recorded remote before this returns. The
    corresponding primary clone, when materialized on disk, is used only as
    a Git object reference for the initial clone.
    """

    from sase.sdd.store import resolve_sdd_store

    store = resolve_sdd_store(Path(primary_checkout), PRIMARY_WORKSPACE_NUM)
    if not store.is_sidecar_storage:
        return ArtifactLinkStore.from_sdd_store(store, project_key)

    hidden_store = _hidden_document_store(project_key, store)
    return ArtifactLinkStore.from_sdd_store(hidden_store, project_key)


@dataclass(frozen=True)
class MachineArtifactLinkRoot:
    """One hidden document sidecar root eligible for machine publication retry."""

    project_key: str
    role: str
    repo_root: Path
    remote_url: str


def machine_document_sidecar_roots(
    project_key: str,
    primary_checkout: str | Path,
) -> tuple[tuple[MachineArtifactLinkRoot, ...], tuple[str, ...]]:
    """Return hidden document sidecar roots without requiring all roles to sync.

    This path is intentionally lazier than
    :func:`resolve_machine_artifact_link_store`: an already-present hidden
    clone is only identity-checked, not freshly integrated, so local-only
    publication work can be observed before any pull/rebase path runs.
    """

    from sase.sdd.store import resolve_sdd_store

    try:
        store = resolve_sdd_store(Path(primary_checkout), PRIMARY_WORKSPACE_NUM)
    except Exception as exc:  # noqa: BLE001 - caller logs per project.
        return (), (f"could not resolve SDD store for publication retry: {exc}",)
    if not store.is_sidecar_storage:
        return (), ()
    return _hidden_document_roots(project_key, store)


def _hidden_document_store(project_key: str, store: SddStore) -> SddStore:
    from sase.linked_repos import hidden_sidecar_clone_dir
    from sase.sdd._store_link import ensure_sidecar_sdd_clone

    document_roles = document_sidecar_roles(
        store.split_sidecar_roles(), include_plans=True
    )
    hidden_dirs: dict[str, Path] = {}
    for role in document_roles:
        remote_url = store.remote_url_for_kind(role)
        if remote_url is None:
            continue
        hidden_dir = Path(hidden_sidecar_clone_dir(project_key, role))
        ensure_sidecar_sdd_clone(
            hidden_dir,
            remote_url,
            reference_repo=_primary_reference_repo(store, role),
            strict=True,
            fresh=True,
        )
        hidden_dirs[role] = hidden_dir

    plans_dir = hidden_dirs.get("plans", store.sdd_dir)
    sidecar_dirs = {
        **store.sidecar_dirs,
        **{role: root for role, root in hidden_dirs.items() if role != "plans"},
    }
    return replace(
        store,
        sdd_dir=plans_dir,
        repo_root=plans_dir,
        sidecar_dirs=sidecar_dirs,
    )


def _hidden_document_roots(
    project_key: str, store: SddStore
) -> tuple[tuple[MachineArtifactLinkRoot, ...], tuple[str, ...]]:
    from sase.linked_repos import hidden_sidecar_clone_dir
    import sase.sdd._store_link as store_link

    roots: list[MachineArtifactLinkRoot] = []
    diagnostics: list[str] = []
    document_roles = document_sidecar_roles(
        store.split_sidecar_roles(), include_plans=True
    )
    for role in document_roles:
        remote_url = store.remote_url_for_kind(role)
        if remote_url is None:
            continue
        hidden_dir = Path(hidden_sidecar_clone_dir(project_key, role))
        try:
            if not _matching_hidden_clone(hidden_dir, remote_url):
                if os.path.lexists(hidden_dir):
                    diagnostics.append(
                        f"{role}: hidden clone missing or has wrong remote; "
                        f"replacing {hidden_dir}"
                    )
                store_link.ensure_sidecar_sdd_clone(
                    hidden_dir,
                    remote_url,
                    reference_repo=_primary_reference_repo(store, role),
                    strict=True,
                    fresh=False,
                )
            if not _matching_hidden_clone(hidden_dir, remote_url):
                diagnostics.append(
                    f"{role}: hidden clone not available for publication retry"
                )
                continue
        except Exception as exc:  # noqa: BLE001 - one role must not block another.
            diagnostics.append(f"{role}: hidden clone unavailable: {exc}")
            continue
        roots.append(
            MachineArtifactLinkRoot(
                project_key=project_key,
                role=role,
                repo_root=hidden_dir.expanduser().resolve(strict=False),
                remote_url=remote_url,
            )
        )
    return tuple(roots), tuple(diagnostics)


def _matching_hidden_clone(root: Path, remote_url: str) -> bool:
    from sase.sdd._store_git import (
        git_remote_url as _git_remote_url,
        same_git_remote as _same_git_remote,
    )

    if not (root / ".git").is_dir():
        return False
    origin = _git_remote_url(root)
    return origin is not None and _same_git_remote(origin, remote_url)


def _primary_reference_repo(store: SddStore, role: str) -> Path | None:
    """Return the primary's materialized clone for *role* as a reference repo.

    ``git clone --reference`` shares Git objects with an already-materialized
    primary clone of the same history, so the hidden clone's first
    materialization does not re-fetch objects the host already has locally.
    """

    try:
        candidate = store.repo_root_for_kind(role)
    except Exception:  # noqa: BLE001 - reference reuse is a best-effort optimization
        return None
    return candidate if (candidate / ".git").is_dir() else None


__all__ = [
    "MachineArtifactLinkRoot",
    "machine_document_sidecar_roots",
    "resolve_machine_artifact_link_store",
]
