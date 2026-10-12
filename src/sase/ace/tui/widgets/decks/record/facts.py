"""Record Lifecycle and Provenance cards (epic sase-1jm.4.2, ``shell``).

Stub bodies until the ``facts`` phase fills them: Lifecycle shows the
agent name, location, and status; Provenance shows the project label
and model. The extras loader runs on the worker thread and currently
returns empty extras without I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text

from ..card_part import CardPart
from .model import RecordSubject


@dataclass(frozen=True)
class FactsExtras:
    """Off-thread Lifecycle/Provenance inputs (filled by ``facts``)."""

    reference: str | None = None
    artifacts_dir: str | None = None
    chat_path: str | None = None
    dismissed_at: str | None = None
    revived_at: str | None = None
    times_revived: int = 0
    bundle_path: str | None = None


def load_facts_extras(subject: RecordSubject) -> FactsExtras:
    """Load Lifecycle/Provenance extras for ``subject`` (worker thread).

    The ``shell`` contract performs no I/O here; the ``facts`` phase
    resolves the ``@agent:`` reference, artifacts dir, chat path, and
    dismissed-bundle rows off-thread.
    """
    del subject
    return FactsExtras()


def lifecycle_card(subject: RecordSubject, extras: FactsExtras) -> CardPart:
    """Build the stub Lifecycle card: name, location, and status."""
    del extras
    lines = [
        Text(f"{subject.agent_name or 'Unnamed agent'}", style="bold"),
        Text(f"Location: {subject.location.title()}", style=""),
        Text(f"Status: {subject.status or '—'}", style=""),
    ]
    return CardPart("lifecycle", "Lifecycle", *lines)


def provenance_card(subject: RecordSubject, extras: FactsExtras) -> CardPart:
    """Build the stub Provenance card: project label and model."""
    del extras
    lines = [
        Text(f"Project: {subject.project_label or '—'}", style=""),
        Text(f"Model: {subject.model or '—'}", style=""),
    ]
    return CardPart("provenance", "Provenance", *lines)


__all__ = [
    "FactsExtras",
    "lifecycle_card",
    "load_facts_extras",
    "provenance_card",
]
