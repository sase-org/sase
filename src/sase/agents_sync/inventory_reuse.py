"""Per-project, per-tick reuse for targeted publication inventory builds."""

from __future__ import annotations

from collections.abc import Callable, Set as AbstractSet
from pathlib import Path

from sase.agents_sync.git import GitRunner
from sase.agents_sync.inventory import build_project_hood_inventory
from sase.agents_sync.inventory_models import ProjectHoodInventory
from sase.agents_sync.models import ProjectTarget
from sase.core.agent_identity_facade import AgentIdentitySnapshot

type InventoryBuilder = Callable[..., ProjectHoodInventory]
type _InputToken = tuple[object, ...]


class ProjectHoodInventoryReuse:
    """Reuse a scoped inventory while its primary and index inputs are stable.

    One instance belongs to one scheduler project pass. Its initial hood set
    is the union of that pass's queued requests, so later 25-row batches can
    share the same inventory without widening the query to unrelated hoods.
    """

    def __init__(
        self,
        requested_hoods: AbstractSet[str],
        *,
        builder: InventoryBuilder = build_project_hood_inventory,
    ) -> None:
        self.requested_hoods = frozenset(requested_hoods)
        self._builder = builder
        self._input_token: _InputToken | None = None
        self._inventory: ProjectHoodInventory | None = None
        self._built_hoods: frozenset[str] = frozenset()

    def build_inventory(
        self,
        target: ProjectTarget,
        identity: AgentIdentitySnapshot,
        *,
        git_runner: GitRunner,
        requested_hoods: AbstractSet[str] | None = None,
    ) -> ProjectHoodInventory:
        requested = self.requested_hoods | frozenset(requested_hoods or ())
        token = _inventory_input_token(target, identity, git_runner)
        if (
            token is not None
            and token == self._input_token
            and self._inventory is not None
            and requested <= self._built_hoods
        ):
            return self._inventory

        inventory = self._builder(
            target,
            identity,
            git_runner=git_runner,
            requested_hoods=requested,
        )
        self._input_token = token
        self._inventory = inventory
        self._built_hoods = requested
        return inventory


def _inventory_input_token(
    target: ProjectTarget,
    identity: AgentIdentitySnapshot,
    git_runner: GitRunner,
) -> _InputToken | None:
    """Return HEAD plus filesystem generations for both queried indexes."""

    head_result = git_runner(
        target.primary_checkout,
        ["rev-parse", "HEAD"],
        op="agents_sync.inventory_reuse_head",
    )
    head = head_result.stdout.strip() if head_result.returncode == 0 else ""
    if not head:
        return None
    try:
        from sase.core.agent_scan_facade import default_agent_artifact_index_path
        from sase.core.dismissed_agents_facade import dismissed_bundles_dir

        artifact_index_path = default_agent_artifact_index_path()
        dismissed_index_path = dismissed_bundles_dir() / "index.sqlite"
        artifact_index = _sqlite_generation(artifact_index_path)
        dismissed_index = _sqlite_generation(dismissed_index_path)
    except (OSError, RuntimeError, ValueError, ImportError):
        return None
    owner = identity.owner
    return (
        target.project_key,
        str(target.primary_checkout.resolve(strict=False)),
        head,
        artifact_index,
        dismissed_index,
        owner.username if owner is not None else None,
        owner.machine_name if owner is not None else None,
        tuple(sorted(identity.known_owner_roots)),
    )


def _path_generation(path: Path) -> tuple[int, int, int, int] | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size)


def _sqlite_generation(path: Path) -> tuple[object, ...]:
    """Include the WAL generation, where committed writes may still live."""

    return (
        _path_generation(path),
        _path_generation(path.with_name(f"{path.name}-wal")),
    )


__all__ = ("ProjectHoodInventoryReuse",)
