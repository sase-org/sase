"""Label a required sidecar protection source that retention cannot read.

Artifact retention requires every enabled project's beads and plans sidecars
as protection sources and fails closed when one is missing. A missing source
has two different causes. Either the project was never connected on this
machine (registered but never launched here, so the ``sidecar_auto_sync``
connect leg has not reached it yet), or a connected project lost one clone.
The label keeps the ``<project>:<role>`` prefix that every reader already
shows, and names the first cause so the diagnostic points at it.
"""

from __future__ import annotations

from sase._repo_inventory_models import RepoRecord
from sase.sdd.store import sdd_store_connected

_UNCONNECTED_NOTE = "sidecars not connected on this machine"


def unavailable_sidecar_label(project: str, role: str, primary: RepoRecord) -> str:
    """Return the unavailable-source label for *project*'s missing *role*.

    *primary* is the project's ``kind == "primary"`` inventory record. An
    unreadable store record keeps the bare label: connecting would not help.
    """

    label = f"{project}:{role}"
    if primary.path and sdd_store_connected(primary.path) is False:
        return f"{label} ({_UNCONNECTED_NOTE})"
    return label


__all__ = ["unavailable_sidecar_label"]
