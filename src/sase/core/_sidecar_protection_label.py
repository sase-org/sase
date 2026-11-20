"""Label a required sidecar protection source that retention cannot read.

Artifact retention requires every enabled sase-managed project's beads and
plans sidecars as protection sources and fails closed when one is missing. A
missing source has two different causes. Either the project was never
connected on this machine (registered but never launched here, so the
``sidecar_auto_sync`` connect leg has not reached it yet), or a connected
project lost one clone. A third case has no required sources at all: the
project is definitively not sase-managed, so it can never connect sidecars
here (see ``sase.sdd.store.sdd_store_not_applicable``). The label keeps the
``<project>:<role>`` prefix that every reader already shows, and names the
first cause so the diagnostic points at it.
"""

from __future__ import annotations

from sase._repo_inventory_models import RepoRecord
from sase.sdd.store import sdd_store_connected, sdd_store_not_applicable

_UNCONNECTED_NOTE = "sidecars not connected on this machine"


def sidecar_protection_not_applicable(primary: RepoRecord) -> bool:
    """Return whether the project's required sidecar sources do not apply.

    *primary* is the project's ``kind == "primary"`` inventory record. True
    only when the project is definitively not sase-managed with no store
    record on this machine; an unreadable ``sase.yml`` or store record fails
    closed (False).
    """

    return bool(primary.path) and sdd_store_not_applicable(primary.path)


def unavailable_sidecar_label(project: str, role: str, primary: RepoRecord) -> str:
    """Return the unavailable-source label for *project*'s missing *role*.

    *primary* is the project's ``kind == "primary"`` inventory record. An
    unreadable store record keeps the bare label: connecting would not help.
    """

    label = f"{project}:{role}"
    if primary.path and sdd_store_connected(primary.path) is False:
        return f"{label} ({_UNCONNECTED_NOTE})"
    return label


#: Directory names pruned from the whole-projects tree walk shared by the
#: artifact-file and ACE-run protection scans. Sidecar roots keep their own
#: narrower coverage; only the projects-tree walk uses this set.
PROJECTS_TREE_SKIP_DIRS = frozenset({".git", "artifacts", "repos"})


__all__ = [
    "PROJECTS_TREE_SKIP_DIRS",
    "sidecar_protection_not_applicable",
    "unavailable_sidecar_label",
]
