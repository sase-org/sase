"""Public collectors for stranded-work reducer input."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sase.bead._stranded_facts_beads import (
    empty_payload,
    payload_for_snapshot,
    titles_for_snapshot,
)
from sase.bead._stranded_facts_snapshot import read_stranded_snapshot
from sase.bead.store_locator import canonical_beads_dir_for_project


def collect_stranded_work_input(
    project: str,
    *,
    now: float | None = None,
    bead_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Build reducer input for *project*, optionally scoped to named beads."""
    payload, _titles, _rebuilt = collect_stranded_work_snapshot(
        project, now=now, bead_ids=bead_ids
    )
    return payload


def collect_issue_titles(
    project: str, *, bead_ids: Iterable[str] | None = None
) -> dict[str, str]:
    """Return bead-id to title for every issue the collector loaded."""
    beads_dir = canonical_beads_dir_for_project(project)
    if beads_dir is None:
        return {}
    candidates, context, _rebuilt = read_stranded_snapshot(project, beads_dir, bead_ids)
    return titles_for_snapshot(candidates, context)


def collect_stranded_work_snapshot(
    project: str,
    *,
    now: float | None = None,
    bead_ids: Iterable[str] | None = None,
) -> tuple[dict[str, Any], dict[str, str], bool]:
    """Collect reducer facts, titles, and whether the stable snapshot rebuilt.

    Facts and titles share one :func:`stranded_snapshot` collection, so a
    report stays coherent when the store changes between what would have
    been separate candidate queries. Unchanged Rust-certified store
    identities reuse the retained candidate/context rows; member liveness
    is always rebuilt.
    """
    moment = float(now) if now is not None else _now_epoch()
    beads_dir = canonical_beads_dir_for_project(project)
    if beads_dir is None:
        return empty_payload(moment), {}, True
    candidates, context, rebuilt = read_stranded_snapshot(project, beads_dir, bead_ids)
    return (
        payload_for_snapshot(project, moment, candidates, context),
        titles_for_snapshot(candidates, context),
        rebuilt,
    )


def _now_epoch() -> float:
    from time import time

    return time()
