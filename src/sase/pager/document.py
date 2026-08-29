"""Structured document model for the link-traversing pager."""

from __future__ import annotations

import io
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal

from rich.console import Console, RenderableType
from rich.text import Text

from sase.pager.link_scan import LinkSpan, LinkSpanKind, PagerOrigin, scan_links

PagerTargetSource = Literal["attached", "scanned"]

_PLAIN_RENDER_WIDTH = 80


@dataclass(frozen=True, slots=True)
class AttachedTarget:
    """Caller-supplied target bound to a span in a pager section."""

    kind: str
    target: object
    start: int
    end: int
    text: str | None = None

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError("attached target kind cannot be empty")
        _validate_span(self.start, self.end, context="attached target")


@dataclass(frozen=True, slots=True)
class PagerTargetSpan:
    """One target occurrence after merging scanned and attached targets."""

    kind: str
    target: object
    start: int
    end: int
    text: str
    source: PagerTargetSource


@dataclass(frozen=True, slots=True)
class PagerSection:
    """One independently navigable section in a pager document."""

    identity: str
    title: str
    kind: str
    body: RenderableType | str
    subject_ref: str | None = None
    targets: tuple[AttachedTarget, ...] = ()
    _body_text: Text = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.identity.strip():
            raise ValueError("pager section identity cannot be empty")
        if not self.title.strip():
            raise ValueError("pager section title cannot be empty")
        if not self.kind.strip():
            raise ValueError("pager section kind cannot be empty")
        body_text = _body_to_text(self.body)
        object.__setattr__(self, "_body_text", body_text)
        targets = tuple(sorted(self.targets, key=_attached_target_sort_key))
        _validate_attached_targets(
            targets,
            body_length=len(body_text.plain),
            section_identity=self.identity,
        )
        object.__setattr__(self, "targets", targets)

    @property
    def plain_text(self) -> str:
        """Return the body text with ANSI control sequences stripped."""
        return self._body_text.plain

    @property
    def body_text(self) -> Text:
        """Return the body as Rich text, preserving ANSI-derived spans."""
        return self._body_text.copy()

    @property
    def body_renderable(self) -> RenderableType:
        """Return the renderable body the pager should paint."""
        if isinstance(self.body, (str, Text)):
            return self._body_text.copy()
        return self.body


@dataclass(frozen=True, slots=True)
class PagerDocument:
    """A pager input document made of stable, navigable sections."""

    sections: tuple[PagerSection, ...]
    title: str
    origin: PagerOrigin

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("pager document title cannot be empty")
        object.__setattr__(self, "sections", tuple(self.sections))

    def iter_target_spans(self) -> Iterator[tuple[PagerSection, PagerTargetSpan]]:
        """Yield merged target spans in document order."""
        for section in self.sections:
            for target in section_target_spans(section, self.origin):
                yield section, target


def target_resolution_ref(target: PagerTargetSpan, origin: PagerOrigin) -> str | None:
    """Return the ref string ``resolve_ref`` should receive for *target*.

    URL spans are never resolved — the press table copies them directly
    (design doc section D6) without ever asking whether they exist. A bare
    token's meaning depends on the document's origin, never globally
    (section D3): a bare id only means a bead in a bead document.
    """
    if target.kind == LinkSpanKind.URL.value:
        return None
    if target.kind == LinkSpanKind.BARE_TOKEN.value:
        return f"bead:{target.text}" if origin is PagerOrigin.BEAD else None
    return target.text


def section_target_spans(
    section: PagerSection,
    origin: PagerOrigin,
) -> tuple[PagerTargetSpan, ...]:
    """Merge scanned spans with caller-attached targets for one section.

    Attached targets win over scanned targets on overlap. The merged tuple is
    sorted by document position so later label allocation can use one shared
    sequence.
    """
    plain = section.plain_text
    attached = tuple(_attached_target_span(target, plain) for target in section.targets)
    attached_ranges = [(target.start, target.end) for target in attached]
    scanned = tuple(
        _scanned_target_span(span)
        for span in scan_links(plain, origin)
        if not _overlaps(span.start, span.end, attached_ranges)
    )
    return tuple(sorted((*attached, *scanned), key=_target_span_sort_key))


def _attached_target_span(target: AttachedTarget, plain: str) -> PagerTargetSpan:
    return PagerTargetSpan(
        kind=target.kind,
        target=target.target,
        start=target.start,
        end=target.end,
        text=target.text
        if target.text is not None
        else plain[target.start : target.end],
        source="attached",
    )


def _scanned_target_span(span: LinkSpan) -> PagerTargetSpan:
    return PagerTargetSpan(
        kind=span.kind.value,
        target=span.text,
        start=span.start,
        end=span.end,
        text=span.text,
        source="scanned",
    )


def _body_to_text(body: RenderableType | str) -> Text:
    if isinstance(body, Text):
        return body.copy()
    if isinstance(body, str):
        text = Text.from_ansi(body)
        _restore_trailing_newlines(text, body)
        return text
    return Text(_render_plain(body))


def _restore_trailing_newlines(text: Text, source: str) -> None:
    """Restore trailing newlines ``Text.from_ansi`` may drop or keep.

    Rich historically strips one trailing newline from ANSI input. Some
    environments keep it. Either way, pager plain text must match the
    source string's trailing-newline count so file and stdin bodies stay
    stable across workers.
    """
    wanted = len(source) - len(source.rstrip("\n"))
    have = len(text.plain) - len(text.plain.rstrip("\n"))
    if have < wanted:
        text.append("\n" * (wanted - have))


def _render_plain(body: RenderableType) -> str:
    capture = io.StringIO()
    console = Console(
        file=capture,
        force_terminal=False,
        color_system=None,
        width=_PLAIN_RENDER_WIDTH,
    )
    console.print(body, end="", highlight=False)
    return capture.getvalue()


def _validate_attached_targets(
    targets: tuple[AttachedTarget, ...],
    *,
    body_length: int,
    section_identity: str,
) -> None:
    previous: AttachedTarget | None = None
    for target in targets:
        if target.end > body_length:
            raise ValueError(
                f"attached target span {target.start}:{target.end} exceeds "
                f"body length {body_length} for section {section_identity}"
            )
        if previous is not None and target.start < previous.end:
            raise ValueError(
                f"attached target span {target.start}:{target.end} overlaps "
                f"{previous.start}:{previous.end} for section {section_identity}"
            )
        previous = target


def _validate_span(start: int, end: int, *, context: str) -> None:
    if start < 0 or end < 0:
        raise ValueError(f"{context} span cannot be negative")
    if start >= end:
        raise ValueError(f"{context} span must be non-empty")


def _overlaps(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    return any(
        start < range_end and range_start < end for range_start, range_end in ranges
    )


def _attached_target_sort_key(target: AttachedTarget) -> tuple[int, int, str]:
    return (target.start, target.end, target.kind)


def _target_span_sort_key(
    target: PagerTargetSpan,
) -> tuple[int, int, int, str]:
    source_order = 0 if target.source == "attached" else 1
    return (target.start, target.end, source_order, target.kind)


__all__ = [
    "AttachedTarget",
    "PagerDocument",
    "PagerOrigin",
    "PagerSection",
    "PagerTargetSpan",
    "PagerTargetSource",
    "section_target_spans",
    "target_resolution_ref",
]
