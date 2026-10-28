"""Shared sidecar-boundary helper for snapshot capture."""

from __future__ import annotations


def is_managed_sidecar_rel(rel: str) -> bool:
    """Whether *rel* lives under the managed sidecar root.

    Clones under ``sase/repos/`` have their own rescue boundaries
    (sidecar/linked/external rescue before eviction), so the main-checkout
    snapshot neither captures nor refuses them.
    """
    return rel == "sase/repos" or rel.startswith("sase/repos/")
