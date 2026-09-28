"""Goal ledger root resolution (epic sase-1bu, phase ledger-root).

A project's ledger lives in one of two places:

- shared: ``<hidden clone of goals.host_role>/goals``, written only through
  the host-owned hidden clone (the ``machine-link-writes-off-primary``
  decision);
- local-only: ``~/.sase/projects/<key>/goals``, a plain directory that is
  never published.

Resolution also stamps the hot-projection header (root pointer) so the fast
``sase goal list`` path can find the ledger without loading config.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.goals.config import goals_host_role, goals_visibility

logger = logging.getLogger(__name__)

GoalLedgerMode = Literal["shared", "local"]


@dataclass(frozen=True)
class GoalLedger:
    """Where one project's goal ledger lives and how it publishes."""

    project: str
    mode: GoalLedgerMode
    root: Path
    host_role: str
    hidden_clone: Path | None
    watermark_path: Path
    outbox_path: Path
    lock_path: Path
    projection_path: Path
    reason: str


def _local_paths(project_key: str) -> tuple[Path, Path, Path, Path, Path]:
    from sase.core.paths import sase_projects_dir

    base = sase_projects_dir() / project_key
    root = base / "goals"
    return (
        root,
        base / "goals.integration",
        base / "goals-outbox.json",
        base / "goals.lock",
        base / "goals-hot.json",
    )


def _local_ledger(project_key: str, host_role: str, reason: str) -> GoalLedger:
    root, watermark, outbox, lock, projection = _local_paths(project_key)
    return GoalLedger(
        project=project_key,
        mode="local",
        root=root,
        host_role=host_role,
        hidden_clone=None,
        watermark_path=watermark,
        outbox_path=outbox,
        lock_path=lock,
        projection_path=projection,
        reason=reason,
    )


def goal_hot_projection_path(project_key: str) -> Path:
    """Return the machine-local hot projection path without resolving.

    Read-only: unlike :func:`resolve_goal_ledger` this never materializes
    clones or stamps headers, so completion rows can call it off the event
    loop.
    """
    from sase.core.paths import sase_projects_dir

    return sase_projects_dir() / project_key / "goals-hot.json"


def resolve_goal_ledger(
    project_key: str, *, deadline: float | None = None
) -> GoalLedger:
    """Resolve *project_key*'s goal ledger, falling back to local-only.

    Shared mode requires ``goals.visibility: shared``, a recorded
    ``goals.host_role`` sidecar with a remote, a materializable hidden
    clone, and a push remote on that clone. Anything else resolves
    local-only with a human-readable ``reason``.
    """
    host_role = goals_host_role()
    if goals_visibility() != "shared":
        return _refresh_projection(
            _local_ledger(
                project_key,
                host_role,
                "goals.visibility is 'local': ledger stays machine-local",
            )
        )

    from sase.bead.workspace import resolve_primary_workspace_for_project

    primary = resolve_primary_workspace_for_project(project_key)
    if primary is None:
        return _refresh_projection(
            _local_ledger(
                project_key, host_role, "no primary checkout: ledger stays local"
            )
        )

    from sase.workspace_provider.store import PRIMARY_WORKSPACE_NUM

    try:
        from sase.sdd.store import resolve_sdd_store

        store = resolve_sdd_store(Path(primary), PRIMARY_WORKSPACE_NUM)
    except Exception as exc:  # noqa: BLE001 - resolution falls back to local.
        logger.warning("goal ledger for %s falls back to local: %s", project_key, exc)
        return _refresh_projection(
            _local_ledger(project_key, host_role, f"could not resolve SDD store: {exc}")
        )
    if not store.is_sidecar_storage:
        return _refresh_projection(
            _local_ledger(
                project_key,
                host_role,
                "project has no sidecar storage: ledger stays local",
            )
        )
    remote_url = store.remote_url_for_kind(host_role)
    if not remote_url:
        return _refresh_projection(
            _local_ledger(
                project_key,
                host_role,
                f"project has no {host_role!r} sidecar: ledger stays local",
            )
        )

    from sase.sdd._artifact_link_machine_store import ensure_hidden_sidecar_clone_root

    hidden, diagnostic = ensure_hidden_sidecar_clone_root(
        project_key, store, host_role, remote_url, deadline=deadline
    )
    if hidden is None:
        return _refresh_projection(
            _local_ledger(
                project_key,
                host_role,
                diagnostic
                or f"hidden {host_role} clone unavailable: ledger stays local",
            )
        )

    from sase.bead._sync_publication import has_push_remote

    if not has_push_remote(hidden):
        return _refresh_projection(
            _local_ledger(
                project_key,
                host_role,
                f"hidden {host_role} clone has no push remote: ledger stays local",
            )
        )

    from sase.core.paths import sase_projects_dir

    ledger = GoalLedger(
        project=project_key,
        mode="shared",
        root=hidden / "goals",
        host_role=host_role,
        hidden_clone=hidden,
        watermark_path=hidden / ".git" / "sase-bead-sync.integration",
        outbox_path=sase_projects_dir() / project_key / "goals-outbox.json",
        lock_path=hidden / "goals.lock",
        projection_path=sase_projects_dir() / project_key / "goals-hot.json",
        reason="",
    )
    return _refresh_projection(ledger)


def _refresh_projection(ledger: GoalLedger) -> GoalLedger:
    """Stamp the projection header so the fast path finds the ledger."""
    from sase.core.goal_ledger_facade import goal_projection_refresh
    from sase.goals.config import goals_fetch_ttl_seconds

    try:
        goal_projection_refresh(
            ledger.root,
            ledger.projection_path,
            ledger.project,
            ledger.mode,
            watermark_path=ledger.watermark_path,
            outbox_path=ledger.outbox_path,
            fetch_ttl_seconds=goals_fetch_ttl_seconds(),
        )
    except Exception as exc:  # noqa: BLE001 - a stale projection never breaks reads.
        logger.warning(
            "goal projection refresh for %s failed (continuing): %s",
            ledger.project,
            exc,
        )
    return ledger
