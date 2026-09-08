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

from dataclasses import replace
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


__all__ = ["resolve_machine_artifact_link_store"]
