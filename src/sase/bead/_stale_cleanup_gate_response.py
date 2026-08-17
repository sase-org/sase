"""Translation of a persisted BeadStaleCleanup response into trusted host input.

Nothing downstream may trust the answering client, so the beads a host effect
acts on are read back out of the persisted request roster rather than taken
from the response. A forged index cannot name a bead the gate never offered.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.bead._stale_cleanup_gate_spec import (
    BEAD_STALE_CLEANUP_CLOSE_OPTION_ID,
    BEAD_STALE_CLEANUP_KIND,
)
from sase.notification_gates.kind_validation.bead_stale_cleanup_payload import (
    parse_bead_stale_cleanup_payload,
)
from sase.notification_gates.models import GateError


@dataclass(frozen=True)
class BeadStaleCleanupResponse:
    """Trusted selected beads translated from a persisted stale-cleanup gate."""

    beads: tuple[tuple[str, str], ...]
    feedback: str | None
    source: str


def translate_bead_stale_cleanup_response(
    bundle_path: Path,
    response: Mapping[str, Any],
) -> BeadStaleCleanupResponse:
    """Translate one persisted BeadStaleCleanup response into trusted host input."""
    from sase.notification_gates.durability import read_json_object

    envelope = read_json_object(bundle_path / "request.json")
    if envelope.get("kind") != BEAD_STALE_CLEANUP_KIND:
        raise GateError(
            "invalid_response",
            str(bundle_path / "request.json"),
            "request is not a bead stale cleanup gate",
        )
    payload = envelope.get("payload")
    if not isinstance(payload, Mapping):
        raise GateError(
            "invalid_response",
            "payload",
            "bead stale cleanup request payload is missing",
        )
    roster = parse_bead_stale_cleanup_payload(payload).beads

    raw_selected = response.get("selected_option_ids")
    if (
        not isinstance(raw_selected, list)
        or len(raw_selected) != 1
        or raw_selected[0] != BEAD_STALE_CLEANUP_CLOSE_OPTION_ID
    ):
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "bead stale cleanup response must select exactly close",
        )
    option_results = response.get("option_results")
    if not isinstance(option_results, list):
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "bead stale cleanup response has no option results",
        )
    result = next(
        (
            entry.get("result")
            for entry in option_results
            if isinstance(entry, Mapping)
            and entry.get("id") == BEAD_STALE_CLEANUP_CLOSE_OPTION_ID
        ),
        None,
    )
    if (
        not isinstance(result, Mapping)
        or result.get("action") != BEAD_STALE_CLEANUP_CLOSE_OPTION_ID
    ):
        raise GateError(
            "invalid_response",
            str(bundle_path / "response.json"),
            "bead stale cleanup response result does not match its selected action",
        )
    indexes = result.get("close_bead_indexes")
    selected = _selected_beads(indexes, roster)

    raw_feedback = response.get("feedback")
    feedback = (
        raw_feedback.strip()
        if isinstance(raw_feedback, str) and raw_feedback.strip()
        else None
    )
    source = response.get("source")
    return BeadStaleCleanupResponse(
        beads=selected,
        feedback=feedback,
        source=source if isinstance(source, str) and source else "host",
    )


def _selected_beads(
    indexes: object,
    roster: tuple[Any, ...],
) -> tuple[tuple[str, str], ...]:
    if not isinstance(indexes, list) or not indexes:
        raise GateError(
            "invalid_response",
            "close_bead_indexes",
            "bead stale cleanup response must name at least one offered bead",
        )
    selected: list[tuple[str, str]] = []
    seen: set[int] = set()
    for raw_index in indexes:
        if isinstance(raw_index, bool) or not isinstance(raw_index, int):
            raise GateError(
                "invalid_response",
                "close_bead_indexes",
                "bead stale cleanup close indexes must be integers",
            )
        if raw_index < 1 or raw_index > len(roster):
            raise GateError(
                "invalid_response",
                "close_bead_indexes",
                "bead stale cleanup response named an index outside the roster",
            )
        if raw_index in seen:
            raise GateError(
                "invalid_response",
                "close_bead_indexes",
                "bead stale cleanup response named a duplicate index",
            )
        seen.add(raw_index)
        bead = roster[raw_index - 1]
        selected.append((bead.project, bead.bead_id))
    return tuple(selected)
