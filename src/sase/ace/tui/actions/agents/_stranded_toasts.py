"""Incident-keyed notifications for newly stranded bead work.

Each stranding incident toasts once. A flap that leaves the stranded set and
comes back with the same incident key stays silent, while a genuine
re-stranding after a new turn carries a new incident key and toasts again.
Bursts above three newly stranded beads collapse into one summary toast.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

_SEEN_LEAVES: dict[str, dict[str, str]] = {}


def _incident_key(verdict: Any) -> str:
    """Return the identity of one stranding incident."""
    return (
        verdict.last_turn_artifact_dir
        or verdict.last_turn
        or verdict.session
        or verdict.bead_id
    )


def announce_stranded_transitions(
    notify: object,
    project_keys: Iterable[str],
) -> list[str]:
    """Toast newly stranded incidents after a warmed report changes.

    The first complete report for each project establishes a quiet startup
    baseline. Degraded reports never establish a baseline and never toast.
    Afterwards only a stranded verdict whose incident key differs from the
    recorded one toasts. Entries are never removed when a bead leaves the
    stranded set, so flaps through absence, ``unknown``, ``blocked``, or
    ``owned`` stay silent. This only reads the in-memory warm cache.
    """
    from sase.ace.tui.models.agent_stranded import cached_stranded_report
    from sase.bead.stranded_presentation import stranded_cause_sentence

    new_leaves: list[tuple[str, str]] = []
    for project_key in sorted(set(project_keys)):
        snapshot = cached_stranded_report(project_key)
        if snapshot is None:
            continue
        if snapshot.degraded:
            continue
        verdicts = {
            verdict.bead_id: verdict
            for verdict in snapshot.report.verdicts
            if verdict.state == "stranded"
        }
        seen = _SEEN_LEAVES.get(project_key)
        if seen is None:
            _SEEN_LEAVES[project_key] = {
                bead_id: _incident_key(verdict) for bead_id, verdict in verdicts.items()
            }
            continue
        for bead_id in sorted(verdicts):
            incident = _incident_key(verdicts[bead_id])
            if seen.get(bead_id) != incident:
                seen[bead_id] = incident
                verdict = verdicts[bead_id]
                turn = (verdict.last_turn or "").rsplit("--", 1)[-1]
                prefix = f"--{turn} " if turn else ""
                new_leaves.append(
                    (
                        bead_id,
                        f"⚐ {bead_id} is stranded: "
                        f"{prefix}{stranded_cause_sentence(verdict)}.",
                    )
                )
    if len(new_leaves) > 3:
        ids = [bead_id for bead_id, _ in new_leaves]
        count = len(ids)
        messages = [
            f"⚐ {count} beads newly stranded: "
            f"{ids[0]}, {ids[1]}, {ids[2]} (+{count - 3} more)."
        ]
    else:
        messages = [message for _, message in new_leaves]
    if callable(notify):
        for message in messages:
            notify(message)  # type: ignore[operator]
    return messages


__all__ = ["announce_stranded_transitions"]
