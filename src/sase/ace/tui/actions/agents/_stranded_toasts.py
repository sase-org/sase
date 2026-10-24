"""Coalesced notifications for newly stranded bead work."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

_SEEN_LEAVES: dict[str, frozenset[str]] = {}


def announce_stranded_transitions(
    notify: object,
    project_keys: Iterable[str],
) -> list[str]:
    """Toast newly stranded leaves after a warmed report changes.

    The first report for each project establishes a quiet startup baseline.
    Subsequent calls compare leaf IDs and emit one deterministic toast per new
    leaf. This only reads the in-memory warm cache.
    """
    from sase.ace.tui.models.agent_stranded import cached_stranded_report
    from sase.bead.stranded_presentation import stranded_cause_sentence

    messages: list[str] = []
    for project_key in sorted(set(project_keys)):
        snapshot = cached_stranded_report(project_key)
        if snapshot is None:
            continue
        current = frozenset(snapshot.report.stranded_ids)
        previous = _SEEN_LEAVES.get(project_key)
        _SEEN_LEAVES[project_key] = current
        if previous is None:
            continue
        verdicts = {
            verdict.bead_id: verdict
            for verdict in snapshot.report.verdicts
            if verdict.state == "stranded"
        }
        for bead_id in sorted(current - previous):
            verdict = verdicts.get(bead_id)
            if verdict is None:
                continue
            turn = (verdict.last_turn or "").rsplit("--", 1)[-1]
            prefix = f"--{turn} " if turn else ""
            messages.append(
                f"⚐ {bead_id} is stranded: {prefix}{stranded_cause_sentence(verdict)}."
            )
    if callable(notify):
        for message in messages:
            notify(message)  # type: ignore[operator]
    return messages


__all__ = ["announce_stranded_transitions"]
