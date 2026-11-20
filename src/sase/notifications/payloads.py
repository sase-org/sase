"""Resolve notification content-addressed payload values through Rust."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path


def resolve_notification_values(
    path: Path | str,
    values: Sequence[str],
) -> list[str | None]:
    """Resolve a batch of action-data values or notes.

    Ordinary inline values pass through unchanged. A reference whose sidecar
    is missing resolves to ``None`` at the same position.
    """
    from sase.core.notification_store_facade import (
        resolve_notification_payloads,
    )

    return resolve_notification_payloads(path, values)


def resolve_notification_value(
    path: Path | str,
    value: str,
) -> str | None:
    """Resolve one action-data value or note, preserving ordinary strings."""
    return resolve_notification_values(path, [value])[0]


def resolve_notification_action_data(
    path: Path | str,
    action_data: Mapping[str, str],
) -> dict[str, str | None]:
    """Resolve all action-data values in one Rust binding call."""
    keys = list(action_data)
    values = resolve_notification_values(path, [action_data[key] for key in keys])
    return dict(zip(keys, values, strict=True))


def resolve_notification_note(path: Path | str, note: str) -> str | None:
    """Resolve one note while leaving an ordinary inline note unchanged."""
    return resolve_notification_value(path, note)


def resolve_notification_notes(
    path: Path | str,
    notes: Sequence[str],
) -> list[str | None]:
    """Resolve notes in order, preserving inline previews for callers to use."""
    return resolve_notification_values(path, notes)


__all__ = [
    "resolve_notification_action_data",
    "resolve_notification_note",
    "resolve_notification_notes",
    "resolve_notification_value",
    "resolve_notification_values",
]
