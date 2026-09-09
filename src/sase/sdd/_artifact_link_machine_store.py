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
import subprocess
import time
from dataclasses import dataclass, replace
from pathlib import Path

from sase.sdd._artifact_link_store_impl import ArtifactLinkStore
from sase.sdd._store_types import (
    SddMaterializationError,
    SddStore,
    document_sidecar_roles,
)
from sase.workspace_provider.store import PRIMARY_WORKSPACE_NUM

_LOCAL_GIT_TIMEOUT_SECONDS = 10.0


def resolve_machine_artifact_link_store(
    project_key: str,
    primary_checkout: str | Path,
    *,
    deadline: float | None = None,
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

    hidden_store = _hidden_document_store(project_key, store, deadline=deadline)
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
    *,
    deadline: float | None = None,
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
    return _hidden_document_roots(project_key, store, deadline=deadline)


def _hidden_document_store(
    project_key: str, store: SddStore, *, deadline: float | None = None
) -> SddStore:
    document_roles = document_sidecar_roles(
        store.split_sidecar_roles(), include_plans=True
    )
    hidden_dirs: dict[str, Path] = {}
    unresolved_sidecars = dict(store.unresolved_sidecars)
    for role in document_roles:
        remote_url = store.remote_url_for_kind(role)
        if remote_url is None:
            continue
        hidden_dir, diagnostic = _ensure_hidden_document_root(
            project_key,
            store,
            role,
            remote_url,
            fresh=True,
            deadline=deadline,
        )
        if hidden_dir is None:
            if role == "plans":
                raise SddMaterializationError(
                    diagnostic or "plans hidden clone is unavailable"
                )
            unresolved_sidecars[role] = (
                diagnostic or f"{role}: hidden clone is unavailable"
            )
            continue
        hidden_dirs[role] = hidden_dir

    plans_dir = hidden_dirs.get("plans", store.sdd_dir)
    document_role_set = frozenset(document_roles)
    sidecar_dirs = {
        **{
            role: root
            for role, root in store.sidecar_dirs.items()
            if role not in document_role_set
        },
        **{role: root for role, root in hidden_dirs.items() if role != "plans"},
    }
    sidecar_remote_urls: dict[str, str] = {
        role: remote_url
        for role, remote_url in store.sidecar_remote_urls.items()
        if role not in document_role_set
    }
    for role in hidden_dirs:
        if role == "plans":
            continue
        remote_url = store.remote_url_for_kind(role)
        if remote_url is not None:
            sidecar_remote_urls[role] = remote_url
    return replace(
        store,
        sdd_dir=plans_dir,
        repo_root=plans_dir,
        sidecar_dirs=sidecar_dirs,
        sidecar_remote_urls=sidecar_remote_urls,
        unresolved_sidecars=unresolved_sidecars,
    )


def _hidden_document_roots(
    project_key: str, store: SddStore, *, deadline: float | None = None
) -> tuple[tuple[MachineArtifactLinkRoot, ...], tuple[str, ...]]:
    roots: list[MachineArtifactLinkRoot] = []
    diagnostics: list[str] = []
    document_roles = document_sidecar_roles(
        store.split_sidecar_roles(), include_plans=True
    )
    for role in document_roles:
        remote_url = store.remote_url_for_kind(role)
        if remote_url is None:
            continue
        hidden_dir, diagnostic = _ensure_hidden_document_root(
            project_key,
            store,
            role,
            remote_url,
            fresh=False,
            deadline=deadline,
        )
        if hidden_dir is None:
            diagnostics.append(
                diagnostic
                or f"{role}: hidden clone not available for publication retry"
            )
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


def _ensure_hidden_document_root(
    project_key: str,
    store: SddStore,
    role: str,
    remote_url: str,
    *,
    fresh: bool,
    deadline: float | None,
) -> tuple[Path | None, str | None]:
    from sase.linked_repos import hidden_sidecar_clone_dir
    from sase.sdd._store_link import ensure_sidecar_sdd_clone

    hidden_dir = Path(hidden_sidecar_clone_dir(project_key, role))
    if _deadline_expired(deadline):
        return None, f"{role}: hidden clone setup deferred past chop budget"

    if os.path.lexists(hidden_dir):
        diagnostic = _hidden_clone_identity_diagnostic(
            role,
            hidden_dir,
            remote_url,
            deadline=deadline,
        )
        if diagnostic is not None:
            return None, diagnostic
        if fresh:
            diagnostic = _fresh_integration_blocker(
                role,
                hidden_dir,
                deadline=deadline,
            )
            if diagnostic is not None:
                return None, diagnostic

    try:
        ensure_sidecar_sdd_clone(
            hidden_dir,
            remote_url,
            reference_repo=_primary_reference_repo(store, role),
            strict=True,
            fresh=fresh,
        )
    except Exception as exc:  # noqa: BLE001 - one role must not block another.
        return None, f"{role}: hidden clone unavailable: {exc}"

    if not _matching_hidden_clone(hidden_dir, remote_url, deadline=deadline):
        return None, f"{role}: hidden clone not available for publication retry"
    return hidden_dir, None


def _hidden_clone_identity_diagnostic(
    role: str,
    root: Path,
    remote_url: str,
    *,
    deadline: float | None,
) -> str | None:
    from sase.sdd._store_git import same_git_remote as _same_git_remote

    if not (root / ".git").is_dir():
        return f"{role}: hidden clone path exists but is not a Git clone; preserving {root}"
    origin = _hidden_clone_origin(root, deadline=deadline)
    if origin is None:
        return (
            f"{role}: hidden clone has no origin remote; preserving {root}; "
            f"configured remote {remote_url}"
        )
    if not _same_git_remote(origin, remote_url):
        return (
            f"{role}: hidden clone remote mismatch; preserving {root}; "
            f"current origin {origin}; configured remote {remote_url}"
        )
    return None


def _fresh_integration_blocker(
    role: str, root: Path, *, deadline: float | None
) -> str | None:
    upstream = _git_text(
        root,
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        deadline=deadline,
    )
    if upstream is None:
        return f"{role}: hidden clone has no tracking upstream; preserving {root}"
    status = _git_result(
        root,
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
        deadline=deadline,
    )
    if status is None or status.returncode != 0:
        return (
            f"{role}: could not inspect hidden clone worktree status; preserving {root}"
        )
    if status.stdout:
        return (
            f"{role}: hidden clone has uncommitted or untracked changes; "
            f"preserving {root}"
        )
    if not _head_is_published(root, deadline=deadline):
        return f"{role}: hidden clone has unpublished commits; preserving {root}"
    return None


def _matching_hidden_clone(
    root: Path, remote_url: str, *, deadline: float | None = None
) -> bool:
    from sase.sdd._store_git import (
        same_git_remote as _same_git_remote,
    )

    if not (root / ".git").is_dir():
        return False
    origin = _hidden_clone_origin(root, deadline=deadline)
    return origin is not None and _same_git_remote(origin, remote_url)


def _hidden_clone_origin(root: Path, *, deadline: float | None = None) -> str | None:
    return _git_text(root, ["remote", "get-url", "origin"], deadline=deadline)


def _head_is_published(root: Path, *, deadline: float | None = None) -> bool:
    result = _git_result(
        root,
        ["merge-base", "--is-ancestor", "HEAD", "@{upstream}"],
        deadline=deadline,
    )
    return result is not None and result.returncode == 0


def _git_text(
    root: Path, args: list[str], *, deadline: float | None = None
) -> str | None:
    result = _git_result(root, args, deadline=deadline)
    if result is None or result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _git_result(
    root: Path, args: list[str], *, deadline: float | None = None
) -> subprocess.CompletedProcess[str] | None:
    timeout = _deadline_timeout(_LOCAL_GIT_TIMEOUT_SECONDS, deadline)
    if timeout <= 0.0:
        return None
    try:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _deadline_expired(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _deadline_timeout(default: float, deadline: float | None) -> float:
    if deadline is None:
        return max(0.0, default)
    return min(max(0.0, default), max(0.0, deadline - time.monotonic()))


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
