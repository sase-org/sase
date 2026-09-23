"""Sidecar protection, agents-sync guard, and launch-time repo setup."""

import contextlib
from collections.abc import Generator
from pathlib import Path

from sase.axe.runner_workspace_beads import protect_workspace_bead_stores
from sase.axe.runner_workspace_sidecar import protect_sidecar_repos


def _agents_sidecar_clone_root(workspace_dir: str | Path) -> Path | None:
    """Return *workspace_dir* when it is the machine-shared agents sidecar clone.

    The agents sidecar lives at one stable machine-level path per project
    (``~/.sase/projects/<key>/repos/agents``) that every numbered workspace
    shares, unlike the per-workspace sidecar clones under ``sase/repos/``.
    """

    from sase.core.paths import sase_projects_dir
    from sase.sdd.store import AGENTS_SIDECAR_ROLE

    path = Path(workspace_dir).expanduser().resolve(strict=False)
    if path.name != AGENTS_SIDECAR_ROLE or path.parent.name != "repos":
        return None
    try:
        projects_root = Path(sase_projects_dir()).expanduser().resolve(strict=False)
    except Exception:  # noqa: BLE001 - path resolution must not break preparation.
        return None
    if path.parent.parent.parent != projects_root:
        return None
    return path if (path / ".git").exists() else None


@contextlib.contextmanager
def agents_sidecar_sync_guard(workspace_dir: str) -> Generator[bool, None, None]:
    """Hold the agents sync lock while preparing the shared agents sidecar.

    ``prepare_workspace`` runs ``git reset --hard HEAD``, ``git clean -fd``, and
    a checkout. Against the shared agents clone those steps race agents sync,
    which stages a whole regenerated payload in the worktree before committing
    it: a reset that rewrites a dirty tracked file unlinks it before recreating
    it, and a publication pass reading the owner manifest inside that window
    sees no file and republishes from an empty manifest, silently truncating it.
    Every agents-sync mutator already serializes on ``sase-agents-sync.lock``,
    so preparation takes the same lock instead of cleaning underneath one.

    Yields ``True`` for any other workspace, which needs no coordination.
    """

    repo = _agents_sidecar_clone_root(workspace_dir)
    if repo is None:
        yield True
        return

    from sase.agents_sync.git import run_git
    from sase.agents_sync.git_sync_ops import (
        agents_git_dir,
        bounded_agents_lock,
        configured_agents_lock_timeout,
    )

    lock_path = agents_git_dir(repo, run_git) / "sase-agents-sync.lock"
    with bounded_agents_lock(lock_path, configured_agents_lock_timeout()) as acquired:
        yield acquired


def protect_unpushed_sidecar_commits(
    workspace_dir: str,
    *,
    evicting: bool = False,
    workspace_num: int = 1,
) -> bool:
    """Publish or rescue local sidecar commits before workspace preparation resets.

    Every direct sidecar clone under ``sase/repos/<role>`` is checked. Bead
    stores keep the specialized semantic-sync path, while other sidecar roles
    use a cheap upstream-ahead probe and direct push. When *evicting*, the
    caller is about to destroy the clones that hold the only copies, so
    unpublishable state is rescued to the durable rescue store outside the
    workspace and eviction always proceeds instead of failing the launch.
    """
    workspace_root = Path(workspace_dir).expanduser().resolve()
    beads_ok, handled_bead_roots = protect_workspace_bead_stores(
        workspace_root,
        evicting=evicting,
        workspace_num=workspace_num,
    )
    sidecar_ok = protect_sidecar_repos(
        workspace_root,
        evicting=evicting,
        workspace_num=workspace_num,
        skip_roots=handled_bead_roots,
    )
    return beads_ok and sidecar_ok


def rescue_sidecars_before_eviction(
    workspace_dir: str, *, workspace_num: int = 1
) -> bool:
    """Publish-or-rescue every sidecar clone before its checkout is destroyed.

    Eviction-mode protection: unpublishable state is rescued to the durable
    rescue store outside the workspace (or loudly warned about) and eviction
    always proceeds instead of failing the launch. Used by last-resort
    workspace re-creation, which is about to move the whole checkout aside.
    """
    return protect_unpushed_sidecar_commits(
        workspace_dir, evicting=True, workspace_num=workspace_num
    )


def prepare_launch_workspace_repos(
    workspace_dir: str,
    workspace_num: int,
) -> frozenset[str]:
    """Evict launch-scoped repos and strictly recreate required sidecars.

    The returned paths identify sidecars proven to have been freshly cloned by
    this launch, so later linked-repo setup can reuse them without another
    materialization or synchronization pass.

    Launch-time sidecar protection publishes once, rescues unpublishable
    state to the durable rescue store outside the workspace, and always
    proceeds with eviction: leftover state from an earlier run never fails a
    new launch.
    """
    from sase.linked_repos import clear_workspace_repos

    # Only numbered workspaces evict sidecars; the primary checkout's clones
    # survive ``clear_workspace_repos`` untouched.
    if workspace_num > 1:
        protect_unpushed_sidecar_commits(
            workspace_dir, evicting=True, workspace_num=workspace_num
        )

    clear_workspace_repos(workspace_dir, workspace_num)

    from sase.sdd._paths import get_primary_workspace_dir
    from sase.sdd._store_records import is_materialized_record, read_sdd_store_record
    from sase.sdd.store import auto_connect_sdd_store, ensure_workspace_sdd_clone

    primary = Path(get_primary_workspace_dir(workspace_dir, workspace_num))
    already_connected = is_materialized_record(read_sdd_store_record(primary))
    if auto_connect_sdd_store(workspace_dir, workspace_num) and not already_connected:
        print("Connected existing SDD sidecars for first use on this machine")

    ensure_workspace_sdd_clone(
        workspace_dir,
        workspace_num,
        strict=workspace_num > 1,
    )

    if workspace_num <= 1:
        return frozenset()
    plans = Path(workspace_dir).expanduser() / "sase" / "repos" / "plans"
    if not (plans / ".git").is_dir():
        return frozenset()
    return frozenset({str(plans.resolve())})


__all__ = [
    "agents_sidecar_sync_guard",
    "protect_unpushed_sidecar_commits",
    "prepare_launch_workspace_repos",
    "rescue_sidecars_before_eviction",
]
