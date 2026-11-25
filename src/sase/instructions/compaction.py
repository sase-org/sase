"""Compile-time compaction of oversize provider root bundles.

When a provider's root slot declares ``max_bytes`` and the delivered text
(the bundle plus its trailing marker line) would exceed it, the compiler
applies a deterministic ladder and stops at the first step that fits:

1. ``superseded_summaries``: superseded entries in always-loaded
   ``roster: list`` memory webs render as one line (number, title, slug,
   supersession marker) with no summary.
2. ``list_rosters``: whole always-loaded ``roster: list`` rosters render one
   line per entry (number, title, slug), largest web first, one web at a
   time.

On-demand webs are omitted from the ladder: their instruction projection
already replaces the roster with a generated pointer, so there is nothing
left to compact.

When neither step fits, the most-compacted bundle is returned and delivery
falls back for ``oversize`` exactly as before. A bundle that already fits
is never touched, and compaction is a projection only: no memory file or
descriptor on disk changes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sase.core.instruction_manifest import INSTRUCTION_MANIFEST_COMPACTION_STEPS
from sase.instructions.sections_base import SectionBuilder, normalize_section_text
from sase.memory.web.models import MemoryWeb
from sase.memory.web.roster import RosterCompaction, render_web_projection_body

#: Ladder step that drops the summaries of superseded list-roster entries.
STEP_SUPERSEDED_SUMMARIES = INSTRUCTION_MANIFEST_COMPACTION_STEPS[0]

#: Ladder step that renders whole list rosters one line per entry.
STEP_LIST_ROSTERS = INSTRUCTION_MANIFEST_COMPACTION_STEPS[1]

_STEP_STYLE: dict[str, RosterCompaction] = {
    STEP_SUPERSEDED_SUMMARIES: "superseded",
    STEP_LIST_ROSTERS: "all",
}

#: Placeholder identity for measuring the delivered marker line; real bundle
#: digests and uuid4 invocation ids have the same lengths.
_PLACEHOLDER_SHA256 = "0" * 64
_PLACEHOLDER_INVOCATION_ID = "00000000-0000-4000-8000-000000000000"


@dataclass(frozen=True)
class CompactableWeb:
    """One included always-loaded ``roster: list`` web the ladder may re-render."""

    section_id: str
    relative_path: str
    web: MemoryWeb


@dataclass(frozen=True)
class _BundleCompaction:
    """Bundle-level record of the ladder step compile applied."""

    step: str
    max_bytes: int
    uncompacted_bytes: int

    def to_wire(self) -> dict[str, Any]:
        """Return the ``bundle.compaction`` manifest mapping."""
        return {
            "step": self.step,
            "max_bytes": self.max_bytes,
            "uncompacted_bytes": self.uncompacted_bytes,
        }


def delivered_bytes(bundle_text: str) -> int:
    """Return the UTF-8 size of *bundle_text* as delivered with its marker."""
    from sase.llm_provider.instruction_delivery import delivered_text

    delivered = delivered_text(
        bundle_text, _PLACEHOLDER_SHA256, _PLACEHOLDER_INVOCATION_ID
    )
    return len(delivered.encode("utf-8"))


def _web_section_text(
    item: CompactableWeb, compaction: RosterCompaction | None
) -> str | None:
    """Return the normalized section text for *item* in one roster style."""
    from sase.amd.inline_memory import inline_memory_section

    body, error = render_web_projection_body(item.web, compaction=compaction)
    if error is not None or body is None:
        return None
    block = inline_memory_section(item.relative_path, body)
    return normalize_section_text(block.strip("\n"))


def _bundle_text(sections: Sequence[SectionBuilder]) -> str:
    return "".join(section.text for section in sections if section.text is not None)


def _byte_length(text: str | None) -> int:
    return len((text or "").encode("utf-8"))


def compact_sections(
    sections: Sequence[SectionBuilder],
    webs: Sequence[CompactableWeb],
    *,
    max_bytes: int | None,
) -> _BundleCompaction | None:
    """Apply the compaction ladder to *sections* in place until they fit.

    Returns ``None`` (and leaves every section untouched) when there is no
    cap, when the delivered text already fits, or when no step changes any
    section. Otherwise each compacted section carries its own
    ``compaction`` record and the returned record names the last step that
    changed the bundle; the bundle may still exceed the cap.
    """
    if max_bytes is None:
        return None
    cap: int = max_bytes
    uncompacted_text = _bundle_text(sections)
    if delivered_bytes(uncompacted_text) <= cap:
        return None

    by_id = {section.id: section for section in sections if section.text is not None}
    candidates: list[tuple[CompactableWeb, SectionBuilder]] = []
    for item in webs:
        section = by_id.get(item.section_id)
        if (
            section is None
            or item.web.roster != "list"
            or item.web.roster_loading != "always"
        ):
            continue
        # Never compact a section whose default re-render does not reproduce
        # its compiled bytes: the projection must start from identical text.
        if _web_section_text(item, None) != section.text:
            continue
        candidates.append((item, section))

    original_lengths = {
        section.id: _byte_length(section.text) for _, section in candidates
    }
    applied_step: str | None = None

    def _apply(item: CompactableWeb, section: SectionBuilder, step: str) -> bool:
        text = _web_section_text(item, _STEP_STYLE[step])
        # A tiny roster can grow once the omission note is appended; a step
        # only ever replaces a section with strictly fewer bytes.
        if text is None or _byte_length(text) >= _byte_length(section.text):
            return False
        section.text = text
        section.compaction = {
            "step": step,
            "uncompacted_length": original_lengths[section.id],
        }
        return True

    def _fits() -> bool:
        return delivered_bytes(_bundle_text(sections)) <= cap

    changed = False
    for item, section in candidates:
        changed = _apply(item, section, STEP_SUPERSEDED_SUMMARIES) or changed
    if changed:
        applied_step = STEP_SUPERSEDED_SUMMARIES

    if applied_step is None or not _fits():
        ordered = sorted(
            candidates,
            key=lambda pair: (-_byte_length(pair[1].text), pair[1].id),
        )
        for item, section in ordered:
            if not _apply(item, section, STEP_LIST_ROSTERS):
                continue
            applied_step = STEP_LIST_ROSTERS
            if _fits():
                break

    if applied_step is None:
        return None
    return _BundleCompaction(
        step=applied_step,
        max_bytes=cap,
        uncompacted_bytes=_byte_length(uncompacted_text),
    )


__all__ = [
    "STEP_LIST_ROSTERS",
    "STEP_SUPERSEDED_SUMMARIES",
    "CompactableWeb",
    "compact_sections",
    "delivered_bytes",
]
