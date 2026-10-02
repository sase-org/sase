"""Paint and match document-scoped link labels for the pager.

The scanner and document model identify target spans without doing I/O.  This
module turns those spans into stable jump hints and a Rich ``Text`` body with
one compact key capsule inserted immediately before each target occurrence.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Iterator, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from typing import Literal

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui._artifact_tab_model import (
    ARTIFACTS_ACCENTS,
    ARTIFACTS_ICONS,
    EXTERNAL_ACCENT,
)
from sase.pager.jump_hints import (
    JUMP_HINT_CHARS,
    PAGER_RESERVED_JUMP_COMMAND_KEYS,
    build_jump_hint_maps,
)
from sase.pager.document import (
    PagerDocument,
    PagerOrigin,
    PagerSection,
    PagerTargetSpan,
    section_line_prefix,
    section_target_spans,
    target_resolution_cache_identity,
    target_resolution_ref,
)
from sase.pager.link_scan import LinkSpanKind

PAGER_LABEL_ALPHABET = "".join(
    char for char in JUMP_HINT_CHARS if char not in PAGER_RESERVED_JUMP_COMMAND_KEYS
)
PAGER_LABEL_TWO_KEY_CAPACITY = len(PAGER_LABEL_ALPHABET) ** 2

_LABEL_STYLE = "bold black on #FFD75F"
_LABEL_MATCH_STYLE = "bold black on #FFFFAF"
_LABEL_DIM_STYLE = "dim"
_LABEL_DANGLING_STYLE = "dim"
_DANGLING_ICON = "⊘"
_DANGLING_ACCENT = "#808080"
_DANGLING_TEXT = "(missing)"
_DEFAULT_LINK_ICON = "•"
_DEFAULT_LINK_ACCENT = EXTERNAL_ACCENT
_PLAN_REF_ICON = "✎"
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
DanglingPredicate = Callable[[int, PagerTargetSpan], bool]


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
    dangling: bool = False


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


def prefix_free_hint_sequence(count: int) -> tuple[str, ...]:
    """Return *count* prefix-free hints in assignment order.

    The pager time band assigns the leading hints to its own targets before
    body targets, so both layers derive from this one sequence.
    """
    _, target_to_hint = build_jump_hint_maps(
        list(range(max(0, count))),
        excluded=PAGER_RESERVED_JUMP_COMMAND_KEYS,
        prefix_free=True,
    )
    return tuple(target_to_hint[index] for index in range(max(0, count)))


def build_label_layer(
    document: PagerDocument,
    *,
    width: int,
    window_scope: LabelWindowScope | None = None,
    section_offsets: Sequence[int] | None = None,
    dangling_refs: AbstractSet[object] = frozenset(),
    is_dangling: DanglingPredicate | None = None,
    hint_offset: int = 0,
) -> PagerLabelLayer:
    """Assign stable labels to pager targets in document order.

    Normal documents use document-scoped labels.  Documents larger than the
    two-key label capacity switch to the dormant window mode and only allocate
    labels for the requested row band. ``hint_offset`` reserves the leading
    hints for chrome targets painted ahead of the body (the time band's
    provenance and cause labels); body labels then continue the same
    sequence so every letter stays stable.
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

    offset = max(0, int(hint_offset))
    sequence = prefix_free_hint_sequence(len(selected) + offset)
    body_hints = sequence[offset:]
    hint_to_label_index = {hint: index for index, hint in enumerate(body_hints)}
    label_index_to_hint = dict(enumerate(body_hints))
    labels = tuple(
        PagerLabel(
            index=index,
            hint=label_index_to_hint[index],
            section_index=occurrence.section_index,
            target=occurrence.target,
            dangling=_target_is_dangling(
                occurrence,
                document=document,
                dangling_refs=dangling_refs,
                is_dangling=is_dangling,
            ),
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


def _target_is_dangling(
    occurrence: _TargetOccurrence,
    *,
    document: PagerDocument,
    dangling_refs: AbstractSet[object],
    is_dangling: DanglingPredicate | None,
) -> bool:
    return _resolve_dangling(
        occurrence.section_index,
        occurrence.target,
        origin=document.origin,
        dangling_refs=dangling_refs,
        is_dangling=is_dangling,
    )


def _resolve_dangling(
    section_index: int,
    target: PagerTargetSpan,
    *,
    origin: PagerOrigin,
    dangling_refs: AbstractSet[object],
    is_dangling: DanglingPredicate | None,
) -> bool:
    if is_dangling is not None:
        return is_dangling(section_index, target)
    return target_resolution_cache_identity(target, origin) in dangling_refs


def _link_accent_style(accent: str, surface: str | None = None) -> str:
    """Return the pager-local ``bold`` link style for *accent*.

    Corrects the artifact-kind accent against *surface* to >= 4.5:1 when
    the surface is a known RGB hex; unknown terminal surfaces keep the
    authored accent. Shared by the labeled body and the search base so
    entering search never changes a link's appearance.
    """

    if surface is None:
        return f"bold {accent}"
    try:
        from sase.pager.syntax_theme import (
            ensure_contrast_min,
            parse_color,
        )

        if parse_color(surface) is None or parse_color(accent) is None:
            return f"bold {accent}"
        corrected = ensure_contrast_min(accent, surface, accent, 4.5)
        return f"bold {corrected}"
    except Exception:
        return f"bold {accent}"


def render_section_with_labels(
    section: PagerSection,
    labels: Sequence[PagerLabel],
    *,
    pending_prefix: str = "",
    source: Text | None = None,
    surface: str | None = None,
) -> Text:
    """Return styled body text with key capsules inserted before labels.

    ``source`` lets prepared syntax-styled text stand in for the section's
    own body text without losing its style spans; the syntax engine
    guarantees it carries the exact same plain text as the section, so
    target offsets computed against ``plain_text`` stay valid.
    """
    body = section.body_text if source is None else source
    if not labels:
        return body

    output = Text(
        style=body.style,
        justify=body.justify,
        overflow=body.overflow,
        no_wrap=body.no_wrap,
        tab_size=body.tab_size,
    )
    cursor = 0
    for label in sorted(labels, key=lambda item: item.target.start):
        start = label.target.start
        end = label.target.end
        output.append_text(body[cursor:start])
        output.append_text(_label_prefix(label, pending_prefix=pending_prefix))
        target = body[start:end]
        marker = _target_marker(label.target, dangling=label.dangling)
        style = (
            _LABEL_DANGLING_STYLE
            if label.dangling
            else _link_accent_style(marker.accent, surface)
        )
        target.stylize(style, 0, len(target.plain))
        output.append_text(target)
        if label.dangling:
            output.append(f" {_DANGLING_TEXT}", style=_LABEL_DANGLING_STYLE)
        cursor = end
    output.append_text(body[cursor:])
    return output


def style_target_accents(
    text: Text,
    section: PagerSection,
    section_index: int,
    origin: PagerOrigin,
    *,
    dangling_refs: AbstractSet[object] = frozenset(),
    is_dangling: DanglingPredicate | None = None,
    surface: str | None = None,
) -> Text:
    """Copy *text* and stylize link target spans with their marker accent.

    No characters are inserted — this is the search-overlay styled base's
    "no capsule" convention, since search matches offsets against the
    unmodified corpus and cannot tolerate label characters moving them.
    """
    styled = text.copy()
    for target in section_target_spans(section, origin):
        dangling = _resolve_dangling(
            section_index,
            target,
            origin=origin,
            dangling_refs=dangling_refs,
            is_dangling=is_dangling,
        )
        marker = _target_marker(target, dangling=dangling)
        style = (
            _LABEL_DANGLING_STYLE
            if dangling
            else _link_accent_style(marker.accent, surface)
        )
        styled.stylize(style, target.start, target.end)
    return styled


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
    marker = _target_marker(label.target, dangling=label.dangling)
    text = Text()
    text.append(
        f"[{label.hint}]",
        style=_label_style(label, pending_prefix=pending_prefix),
    )
    icon_style = _label_icon_style(label, marker, pending_prefix=pending_prefix)
    text.append(f"{marker.icon}{_NO_BREAK_SPACE}", style=icon_style)
    return text


def _label_icon_style(
    label: PagerLabel,
    marker: _TargetMarker,
    *,
    pending_prefix: str,
) -> str:
    if label.dangling:
        return _LABEL_DANGLING_STYLE
    if pending_prefix and not label.hint.startswith(pending_prefix):
        return f"{_LABEL_DIM_STYLE} bold {marker.accent}"
    return f"bold {marker.accent}"


def _label_style(label: PagerLabel, *, pending_prefix: str) -> str:
    if label.dangling:
        return _LABEL_DANGLING_STYLE
    if not pending_prefix:
        return _LABEL_STYLE
    hint = label.hint
    return _LABEL_MATCH_STYLE if hint.startswith(pending_prefix) else _LABEL_DIM_STYLE


def _target_marker(target: PagerTargetSpan, *, dangling: bool) -> _TargetMarker:
    if dangling:
        return _TargetMarker(_DANGLING_ICON, _DANGLING_ACCENT)

    if target.kind == LinkSpanKind.URL.value:
        return _TargetMarker(_URL_ICON, EXTERNAL_ACCENT)

    attachment_marker = _attachment_target_marker(target)
    if attachment_marker is not None:
        return attachment_marker

    tab = _target_artifact_tab(target)
    if tab is None:
        return _TargetMarker(_DEFAULT_LINK_ICON, _DEFAULT_LINK_ACCENT)
    if tab == "ref:plan":
        return _TargetMarker(_PLAN_REF_ICON, ARTIFACTS_ACCENTS[tab])
    return _TargetMarker(
        ARTIFACTS_ICONS.get(tab, _DEFAULT_LINK_ICON),
        ARTIFACTS_ACCENTS.get(tab, _DEFAULT_LINK_ACCENT),
    )


_ATTACHMENT_ICONS: dict[str, tuple[str, str]] = {
    "image": ("🖼", "#FFAF5F"),
    "video": ("🎞", "#FFAF5F"),
    "pdf": ("📕", "#FFAF5F"),
    "text": ("≡", "#FFAF5F"),
    "archive": ("▤", "#FFAF5F"),
    "audio": ("♫", "#FFAF5F"),
    "other": ("◇", "#FFAF5F"),
    "attachment": ("📎", "#FFAF5F"),
}

_ATTACHMENT_SUFFIX_ICONS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (
        (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif"),
        "🖼",
        "#FFAF5F",
    ),
    ((".mp4", ".mov", ".mkv", ".webm", ".ogv"), "🎞", "#FFAF5F"),
    ((".mp3", ".wav", ".flac", ".ogg", ".opus"), "♫", "#FFAF5F"),
    ((".pdf",), "📕", "#FFAF5F"),
    (
        (
            ".md",
            ".txt",
            ".log",
            ".json",
            ".jsonl",
            ".yaml",
            ".yml",
            ".toml",
            ".csv",
            ".diff",
            ".patch",
            ".py",
            ".rs",
            ".ts",
            ".sh",
        ),
        "≡",
        "#FFAF5F",
    ),
    ((".zip", ".tar", ".gz", ".bz2", ".xz", ".zst", ".7z"), "▤", "#FFAF5F"),
)


def _attachment_target_marker(target: PagerTargetSpan) -> _TargetMarker | None:
    """Return the attachment icon for ``attachment:`` refs, else ``None``."""
    ref = target.target if isinstance(target.target, str) else target.text
    if not isinstance(ref, str) or not ref.lower().startswith("attachment:"):
        return None
    payload = ref.split(":", 1)[1] if ":" in ref else ""
    name = payload.rsplit("/", 1)[-1].lower() if payload else ""
    for suffixes, icon, accent in _ATTACHMENT_SUFFIX_ICONS:
        if name.endswith(suffixes):
            return _TargetMarker(icon, accent)
    icon, accent = _ATTACHMENT_ICONS["attachment"]
    return _TargetMarker(icon, accent)


def _target_artifact_tab(target: PagerTargetSpan) -> str | None:
    if target.kind == LinkSpanKind.ARTIFACT_REF.value:
        ref = target.target if isinstance(target.target, str) else target.text
        ref_kind = ref.split(":", 1)[0].lower()
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
    return offset + _section_row_for_character_offset(
        section, occurrence.target.start, width
    )


def _row_for_character_offset(text: str, offset: int, width: int) -> int:
    """Estimate the wrapped row containing ``offset`` with no I/O.

    This is the exact-semantics oracle: the cached section path must agree
    with it on every offset, which the label parity tests prove on fixed
    random inputs.
    """
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


def _section_row_for_character_offset(
    section: PagerSection, offset: int, width: int
) -> int:
    """Estimate the wrapped row containing ``offset`` in *section*.

    Identical results to :func:`_row_for_character_offset` on the section's
    plain text: the memoized per-line prefix supplies the row at the
    containing line's start, and only that line's fragment is walked
    through the same estimator. Each call costs O(log lines + line length)
    instead of O(offset).
    """
    text = section.plain_text
    clamped = max(0, min(int(offset), len(text)))
    line_starts, start_rows = section_line_prefix(section, width)
    line = max(0, bisect_right(line_starts, clamped) - 1)
    fragment = text[line_starts[line] : clamped]
    return start_rows[line] + _row_for_character_offset(fragment, len(fragment), width)


__all__ = [
    "LabelWindowScope",
    "PAGER_LABEL_ALPHABET",
    "PAGER_LABEL_TWO_KEY_CAPACITY",
    "PagerLabel",
    "PagerLabelLayer",
    "build_label_layer",
    "prefix_free_hint_sequence",
    "render_section_with_labels",
    "style_target_accents",
]
