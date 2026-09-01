"""Parse and format memory-strand supersession metadata.

This module imports only from ``.models`` (and stdlib) so roster rendering can
use it without an import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import MemoryStrand

SUPERSEDED_STATUS = "superseded"
SUPERSEDED_IN_PART_STATUS = "superseded-in-part"
SUPERSESSION_STATUSES = frozenset({SUPERSEDED_STATUS, SUPERSEDED_IN_PART_STATUS})


@dataclass(frozen=True, slots=True)
class StrandSupersession:
    """A recognized supersession declaration on one strand."""

    status: str
    partial: bool
    superseded_by: tuple[str, ...]


def supersession_status(value: object) -> str | None:
    """Return a recognized supersession status, or ``None``."""

    if not isinstance(value, str):
        return None
    status = value.strip()
    return status if status in SUPERSESSION_STATUSES else None


def coerce_superseded_by_targets(value: object) -> tuple[str, ...] | None:
    """Return normalized successor targets, ``()`` if empty, or ``None`` if malformed."""

    if value is None:
        return ()
    if isinstance(value, str):
        stripped = value.strip()
        return (stripped,) if stripped else None
    if isinstance(value, list):
        targets: list[str] = []
        for item in value:
            if not isinstance(item, str):
                return None
            stripped = item.strip()
            if not stripped:
                return None
            targets.append(stripped)
        return tuple(targets)
    return None


def parse_strand_supersession(strand: MemoryStrand) -> StrandSupersession | None:
    """Return a recognized supersession, or ``None`` when absent or malformed."""

    metadata: dict[str, Any] = strand.metadata
    status = supersession_status(metadata.get("status"))
    if status is None:
        return None
    targets = coerce_superseded_by_targets(metadata.get("superseded_by"))
    if not targets:
        return None
    return StrandSupersession(
        status=status,
        partial=status == SUPERSEDED_IN_PART_STATUS,
        superseded_by=targets,
    )


def format_roster_supersession_marker(
    supersession: StrandSupersession, *, web_slug: str
) -> str:
    """Return the list-roster italic marker, stripping a same-web slash prefix."""

    verb = "partly superseded by" if supersession.partial else "superseded by"
    addresses = ", ".join(
        f"`{_roster_successor_display(address, web_slug)}`"
        for address in supersession.superseded_by
    )
    # Underscores, not asterisks: Prettier rewrites `*italic*` to `_italic_` in
    # managed roster regions and would otherwise fight `sase memory init`.
    return f"_[{verb} {addresses}]_"


def format_inline_roster_supersession_suffix(supersession: StrandSupersession) -> str:
    """Return the bare inline-roster suffix, with no successor list."""

    return "[partly superseded]" if supersession.partial else "[superseded]"


def _roster_successor_display(address: str, web_slug: str) -> str:
    prefix = f"{web_slug}/"
    if address.startswith(prefix):
        return address[len(prefix) :]
    return address


__all__ = [
    "SUPERSEDED_IN_PART_STATUS",
    "SUPERSEDED_STATUS",
    "SUPERSESSION_STATUSES",
    "StrandSupersession",
    "coerce_superseded_by_targets",
    "format_inline_roster_supersession_suffix",
    "format_roster_supersession_marker",
    "parse_strand_supersession",
    "supersession_status",
]
