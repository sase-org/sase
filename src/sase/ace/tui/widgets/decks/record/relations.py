"""Record Relations and Links cards (epic sase-1jm.4.2, ``shell``).

Stub bodies until the ``relations`` phase fills them: Relations shows
an em dash and Links shows the empty state. The extras loader runs on
the worker thread and currently returns empty extras without I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rich.text import Text

from ..card_part import CardPart
from .model import RecordSubject


@dataclass(frozen=True)
class RelationsExtras:
    """Off-thread Relations/Links inputs (filled by ``relations``)."""

    resolved_names: tuple[tuple[str, str], ...] = ()
    link_groups: tuple[tuple[str, tuple[str, ...]], ...] = ()
    snapshot_source_key: str | None = None
    snapshot_error: str | None = None
    extra_chips: tuple[str, ...] = field(default_factory=tuple)


def load_relations_extras(subject: RecordSubject) -> RelationsExtras:
    """Load Relations/Links extras for ``subject`` (worker thread).

    The ``shell`` contract performs no I/O here; the ``relations``
    phase resolves live and dismissed references and reads the shared
    cached link index off-thread.
    """
    del subject
    return RelationsExtras()


def relations_card(subject: RecordSubject, extras: RelationsExtras) -> CardPart:
    """Build the stub Relations card."""
    del subject, extras
    return CardPart("relations", "Relations", Text("—", style="dim"))


def links_card(subject: RecordSubject, extras: RelationsExtras) -> CardPart:
    """Build the stub Links card."""
    del subject, extras
    return CardPart("links", "Links", Text("No artifact links", style="dim italic"))


__all__ = [
    "RelationsExtras",
    "links_card",
    "load_relations_extras",
    "relations_card",
]
