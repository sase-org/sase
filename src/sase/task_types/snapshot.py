"""Committed catalog snapshot assembly (D6) for ``sase memory init``.

The snapshot is the deterministic, git-committed render source for the
generated task-type memory note: every catalog member, keyed by the same
digest ``sase bead task-type show`` already reports, so a project's committed
configuration -- not whichever plugins happen to be installed locally --
decides what the note documents.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.core.rust import require_rust_binding

from ._models import TaskTypeRecord, TaskTypeRegistry


def task_type_snapshot_entry(record: TaskTypeRecord) -> dict[str, Any]:
    """Return one ``TaskTypeSnapshotEntryWire``-shaped dict for *record*."""

    spec = record.spec
    return {
        "task_type": record.task_type,
        "label": spec.get("label", record.task_type),
        "summary": spec.get("summary", ""),
        "when_to_use": spec.get("when_to_use", ""),
        "glyph": spec.get("glyph"),
        "accent_color": spec.get("accent_color"),
        "agent_creatable": record.agent_creatable,
        "default_size": spec.get("default_size"),
        "fields": [dict(field) for field in spec.get("fields", ())],
        "body_template": spec.get("body_template"),
        "triage": dict(spec.get("triage") or {"min_plus_ones": 0}),
        "source": record.provenance.source,
        "package": record.provenance.package,
        "digest": record.digest,
    }


def build_task_type_snapshot_entries(
    registry: TaskTypeRegistry,
) -> tuple[dict[str, Any], ...]:
    """Return every registry record as a sorted snapshot entry."""

    entries = [task_type_snapshot_entry(record) for record in registry.records]
    entries.sort(key=lambda entry: str(entry["task_type"]))
    return tuple(entries)


def render_task_type_snapshot_json(entries: Sequence[Mapping[str, Any]]) -> str:
    """Serialize *entries* through the deterministic Rust snapshot codec."""

    payload = {"types": [dict(entry) for entry in entries]}
    return str(require_rust_binding("serialize_task_type_snapshot")(payload))


__all__ = [
    "build_task_type_snapshot_entries",
    "render_task_type_snapshot_json",
    "task_type_snapshot_entry",
]
