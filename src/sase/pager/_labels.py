"""Paint and match document-scoped link labels for the pager.

The scanner and document model identify target spans without doing I/O.  This
module turns those spans into stable jump hints and a Rich ``Text`` body with
one compact key capsule inserted immediately before each target occurrence.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui._artifact_tab_model import (
    ARTIFACTS_ACCENTS,
    ARTIFACTS_ICONS,
    EXTERNAL_ACCENT,
)
from sase.ace.tui.actions.navigation.jump_hints import (
    JUMP_HINT_CHARS,
    PAGER_RESERVED_JUMP_COMMAND_KEYS,
    build_jump_hint_maps,
)
from sase.pager.document import PagerDocument, PagerSection, PagerTargetSpan
from sase.pager.document import section_target_spans
from sase.pager.link_scan import LinkSpanKind

PAGER_LABEL_ALPHABET = "".join(
    char for char in JUMP_HINT_CHARS if char not in PAGER_RESERVED_JUMP_COMMAND_KEYS
)
PAGER_LABEL_TWO_KEY_CAPACITY = len(PAGER_LABEL_ALPHABET) ** 2

_LABEL_STYLE = "bold black on #FFD75F"
_LABEL_MATCH_STYLE = "bold black on #FFFFAF"
_LABEL_DIM_STYLE = "dim"
_DEFAULT_LINK_ICON = "◆"
_DEFAULT_LINK_ACCENT = "#AFAFAF"
_URL_ICON = "↗"
_NO_BREAK_SPACE = "\u00a0"

_REF_KIND_TABS: Mapping[str, str] = {
    "agent": "agents",
    "bead": "beads",
    "file": "files",
    "patch": "patches",
    "plan": "ref:plan",
    "stitch": "stitches",
}
_DIRECT_KIND_TABS: Mapping[str, str] = {
    **_REF_KIND_TABS,
    "agents": "agents",
    "beads": "beads",
    "files": "files",
    "patches": "patches",
    "stitches": "stitches",
    LinkSpanKind.FILE_PATH.value: "files",
}


LabelLayerMode = Literal["document", "window"]


@dataclass(frozen=True, slots=True)
class LabelWindowScope:
    """A dormant fallback band for documents past two-key label capacity."""

    start_row: int
    end_row: int

    def __post_init__(self) -> None:
        if self.start_row < 0:
            raise ValueError("label window start row cannot be negative")
        if self.end_row <= self.start_row:
            raise ValueError("label window end row must be after start row")

    def contains(self, row: int) -> bool:
        return self.start_row <= row < self.end_row


@dataclass(frozen=True, slots=True, eq=False)
class PagerLabel:
    """One painted label bound to one target occurrence."""

    index: int
    hint: str
    section_index: int
    target: PagerTargetSpan


@dataclass(frozen=True, slots=True)
class PagerLabelLayer:
    """Generated labels and lookup maps for one pager document."""

    labels: tuple[PagerLabel, ...]
    hint_to_label_index: Mapping[str, int]
    labels_by_section: tuple[tuple[PagerLabel, ...], ...]
    target_count: int
    mode: LabelLayerMode
    window_scope: LabelWindowScope | None = None

    @property
    def has_labels(self) -> bool:
        return bool(self.labels)

    @property
    def visible_label_count(self) -> int:
        return len(self.labels)


@dataclass(frozen=True, slots=True)
class _TargetOccurrence:
    section_index: int
    target: PagerTargetSpan


@dataclass(frozen=True, slots=True)
class _TargetMarker:
    icon: str
    accent: str


def build_label_layer(
    document: PagerDocument,
    *,
    width: int,
    window_scope: LabelWindowScope | None = None,
    section_offsets: Sequence[int] | None = None,
) -> PagerLabelLayer:
    """Assign stable labels to pager targets in document order.

    Normal documents use document-scoped labels.  Documents larger than the
    two-key label capacity switch to the dormant window mode and only allocate
    labels for the requested row band.
    """
    occurrences = tuple(_iter_target_occurrences(document))
    mode: LabelLayerMode = (
        "window" if len(occurrences) > PAGER_LABEL_TWO_KEY_CAPACITY else "document"
    )
    selected = occurrences
    if mode == "window":
        scope = window_scope or LabelWindowScope(0, max(1, width))
        offsets = tuple(section_offsets or ())
        selected = tuple(
            occurrence
            for occurrence in occurrences
            if scope.contains(_occurrence_row(document, occurrence, width, offsets))
        )[:PAGER_LABEL_TWO_KEY_CAPACITY]
    else:
        scope = None

    target_ids = list(range(len(selected)))
    hint_to_label_index, label_index_to_hint = build_jump_hint_maps(
        target_ids,
        excluded=PAGER_RESERVED_JUMP_COMMAND_KEYS,
        prefix_free=True,
    )
    labels = tuple(
        PagerLabel(
            index=index,
            hint=label_index_to_hint[index],
            section_index=occurrence.section_index,
            target=occurrence.target,
        )
        for index, occurrence in enumerate(selected)
        if index in label_index_to_hint
    )
    return PagerLabelLayer(
        labels=labels,
        hint_to_label_index=hint_to_label_index,
        labels_by_section=_group_labels_by_section(labels, len(document.sections)),
        target_count=len(occurrences),
        mode=mode,
        window_scope=scope,
    )


def render_section_with_labels(
    section: PagerSection,
    labels: Sequence[PagerLabel],
    *,
    pending_prefix: str = "",
) -> Text:
    """Return ``section`` body text with key capsules inserted before labels."""
    if not labels:
        return section.body_text

    source = section.body_text
    output = Text(
        style=source.style,
        justify=source.justify,
        overflow=source.overflow,
        no_wrap=source.no_wrap,
        tab_size=source.tab_size,
    )
    cursor = 0
    for label in sorted(labels, key=lambda item: item.target.start):
        start = label.target.start
        end = label.target.end
        output.append_text(source[cursor:start])
        output.append_text(_label_prefix(label, pending_prefix=pending_prefix))
        target = source[start:end]
        marker = _target_marker(label.target)
        target.stylize(f"bold {marker.accent}", 0, len(target.plain))
        output.append_text(target)
        cursor = end
    output.append_text(source[cursor:])
    return output


def _iter_target_occurrences(document: PagerDocument) -> Iterator[_TargetOccurrence]:
    for section_index, section in enumerate(document.sections):
        for target in section_target_spans(section, document.origin):
            yield _TargetOccurrence(section_index=section_index, target=target)


def _group_labels_by_section(
    labels: tuple[PagerLabel, ...],
    section_count: int,
) -> tuple[tuple[PagerLabel, ...], ...]:
    buckets: list[list[PagerLabel]] = [[] for _ in range(section_count)]
    for label in labels:
        buckets[label.section_index].append(label)
    return tuple(tuple(bucket) for bucket in buckets)


def _label_prefix(label: PagerLabel, *, pending_prefix: str) -> Text:
    marker = _target_marker(label.target)
    style = _label_style(label.hint, pending_prefix=pending_prefix)
    text = Text(f"[{label.hint}]", style=style)
    text.append(f"{marker.icon}{_NO_BREAK_SPACE}", style=f"bold {marker.accent}")
    return text


def _label_style(hint: str, *, pending_prefix: str) -> str:
    if not pending_prefix:
        return _LABEL_STYLE
    return _LABEL_MATCH_STYLE if hint.startswith(pending_prefix) else _LABEL_DIM_STYLE


def _target_marker(target: PagerTargetSpan) -> _TargetMarker:
    if target.kind == LinkSpanKind.URL.value:
        return _TargetMarker(_URL_ICON, EXTERNAL_ACCENT)

    tab = _target_artifact_tab(target)
    if tab is None:
        return _TargetMarker(_DEFAULT_LINK_ICON, _DEFAULT_LINK_ACCENT)
    return _TargetMarker(
        ARTIFACTS_ICONS.get(tab, _DEFAULT_LINK_ICON),
        ARTIFACTS_ACCENTS.get(tab, _DEFAULT_LINK_ACCENT),
    )


def _target_artifact_tab(target: PagerTargetSpan) -> str | None:
    if target.kind == LinkSpanKind.ARTIFACT_REF.value:
        ref_kind = target.text.split(":", 1)[0].lower()
        return _REF_KIND_TABS.get(ref_kind)
    if target.kind == LinkSpanKind.BARE_TOKEN.value:
        return "beads" if target.text.startswith("sase-") else "patches"
    return _DIRECT_KIND_TABS.get(target.kind.lower())


def _occurrence_row(
    document: PagerDocument,
    occurrence: _TargetOccurrence,
    width: int,
    section_offsets: tuple[int, ...],
) -> int:
    section = document.sections[occurrence.section_index]
    offset = (
        section_offsets[occurrence.section_index]
        if occurrence.section_index < len(section_offsets)
        else 0
    )
    return offset + _row_for_offset(section.plain_text, occurrence.target.start, width)


def _row_for_offset(text: str, offset: int, width: int) -> int:
    """Estimate the wrapped row containing ``offset`` with no I/O."""
    row = 0
    column = 0
    max_width = max(width, 1)
    for character in text[:offset]:
        if character == "\n":
            row += 1
            column = 0
            continue
        cell_width = max(cell_len(character), 1)
        if column + cell_width > max_width:
            row += 1
            column = 0
        column += cell_width
    return row


__all__ = [
    "LabelWindowScope",
    "PAGER_LABEL_ALPHABET",
    "PAGER_LABEL_TWO_KEY_CAPACITY",
    "PagerLabel",
    "PagerLabelLayer",
    "build_label_layer",
    "render_section_with_labels",
]
