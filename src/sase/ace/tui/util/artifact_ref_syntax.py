"""Shared artifact-reference syntax spans for ACE prompt surfaces."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, Protocol

from rich.style import Style
from rich.style import StyleType

from sase.artifact_refs import (
    ArtifactRefPromptCandidate,
    ArtifactRefSpan,
    scan_artifact_refs,
)
from sase.xprompt._literal_zones import literal_zone_ranges
from sase.xprompt.highlight_theme import derive_argument_color

ArtifactRefPartRole = Literal[
    "sigil",
    "kind",
    "separator",
    "delimiter",
    "payload",
    "fragment",
]
ArtifactRefPresentation = Literal["known", "unknown", "neutral", "malformed"]
ArtifactRefStyleKey = Literal[
    "sigil",
    "kind",
    "separator",
    "delimiter",
    "payload",
    "fragment",
    "unknown",
    "neutral",
    "error",
]

_ARTIFACT_REF_STYLE_ORDER: tuple[ArtifactRefStyleKey, ...] = (
    "sigil",
    "kind",
    "separator",
    "delimiter",
    "payload",
    "fragment",
    "unknown",
    "neutral",
    "error",
)
_FALLBACK_THEME = MappingProxyType(
    {
        "secondary": "#87AFFF",
        "success": "#87D787",
        "accent": "#D787FF",
        "error": "#FF5F5F",
        "foreground": "#F8F8F2",
        "background": "#000000",
    }
)


class _StylizableText(Protocol):
    def stylize(
        self,
        style: StyleType,
        start: int = 0,
        end: int | None = None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ArtifactRefPartSpan:
    """One character-offset artifact-reference part span."""

    role: ArtifactRefPartRole
    span: ArtifactRefSpan


@dataclass(frozen=True, slots=True)
class ArtifactRefCandidateSpans:
    """A scanner candidate converted to Python character offsets."""

    candidate: ArtifactRefPromptCandidate
    candidate_span: ArtifactRefSpan
    parts: tuple[ArtifactRefPartSpan, ...]
    presentation: ArtifactRefPresentation

    @property
    def kind(self) -> str:
        return self.candidate.kind

    @property
    def well_formed(self) -> bool:
        return self.candidate.well_formed


@dataclass(frozen=True, slots=True)
class ArtifactRefStyledSpan:
    """A character-offset span paired with an artifact-ref style key."""

    span: ArtifactRefSpan
    style_key: ArtifactRefStyleKey

    @property
    def style_name(self) -> str:
        return f"artifact_ref.{self.style_key}"


@dataclass(frozen=True, slots=True)
class ArtifactRefStylePalette:
    """Theme-derived Rich styles for artifact-reference roles."""

    styles: Mapping[str, Style]
    signature: str

    def style_for_key(self, key: ArtifactRefStyleKey) -> Style:
        return self.styles[f"artifact_ref.{key}"]


def artifact_ref_style_palette_from_theme(
    theme: Any | None,
) -> ArtifactRefStylePalette:
    """Return artifact-reference styles derived from *theme*.

    The fallback values mirror the existing xprompt visual language so unit
    tests and non-mounted render paths still get stable styling.
    """
    background = _theme_color(theme, "background")
    foreground = _theme_color(theme, "foreground")
    secondary = _theme_color(theme, "secondary")
    success = _theme_color(theme, "success")
    accent = _theme_color(theme, "accent")
    error = _theme_color(theme, "error")
    argument_color = derive_argument_color(
        success,
        foreground=foreground,
        background=background,
    )
    fragment_color = derive_argument_color(
        accent,
        foreground=foreground,
        background=background,
    )
    styles = {
        "artifact_ref.sigil": Style(color=secondary, bold=True),
        "artifact_ref.kind": Style(color=success, bold=True),
        "artifact_ref.separator": Style(color=secondary, dim=True, bold=True),
        "artifact_ref.delimiter": Style(color=secondary, dim=True),
        "artifact_ref.payload": Style(color=argument_color),
        "artifact_ref.fragment": Style(color=fragment_color, italic=True),
        "artifact_ref.unknown": Style(color=foreground, dim=True, italic=True),
        "artifact_ref.neutral": Style(color=secondary, dim=True),
        "artifact_ref.error": Style(color=error, underline=True),
    }
    return ArtifactRefStylePalette(
        styles=MappingProxyType(styles),
        signature="|".join(
            f"{key}:{_style_signature(styles[f'artifact_ref.{key}'])}"
            for key in _ARTIFACT_REF_STYLE_ORDER
        ),
    )


def build_artifact_ref_candidate_spans(
    text: str,
    *,
    known_kinds: frozenset[str] | None,
    max_bytes: int,
    max_lines: int,
) -> tuple[ArtifactRefCandidateSpans, ...]:
    """Return scanner candidates as character-offset presentation spans.

    This helper is deliberately fail-open: scanner failures, stale wire data, or
    unexpected byte offsets produce no overlays rather than corrupting text.
    """
    if "@" not in text:
        return ()
    try:
        encoded = text.encode("utf-8")
        if len(encoded) > max_bytes or text.count("\n") > max_lines:
            return ()
        scanner_candidates = scan_artifact_refs(text)
        if not scanner_candidates:
            return ()
        literal_ranges = literal_zone_ranges(text)
        converted = _candidate_character_spans(text, encoded, scanner_candidates)
    except Exception:
        return ()

    result: list[ArtifactRefCandidateSpans] = []
    literal_index = 0
    for candidate, spans in zip(scanner_candidates, converted, strict=True):
        candidate_span = spans["candidate"]
        while (
            literal_index < len(literal_ranges)
            and literal_ranges[literal_index][1] <= candidate_span.start
        ):
            literal_index += 1
        if (
            literal_index < len(literal_ranges)
            and literal_ranges[literal_index][0] < candidate_span.end
        ):
            continue
        result.append(
            ArtifactRefCandidateSpans(
                candidate=candidate,
                candidate_span=candidate_span,
                parts=tuple(
                    ArtifactRefPartSpan(role=role, span=span)
                    for role, span in _candidate_parts(spans)
                ),
                presentation=_presentation(candidate, known_kinds),
            )
        )
    return tuple(result)


def artifact_ref_styled_spans(
    candidates: tuple[ArtifactRefCandidateSpans, ...],
) -> tuple[ArtifactRefStyledSpan, ...]:
    """Return the Rich/TextArea overlay spans for converted candidates."""
    spans: list[ArtifactRefStyledSpan] = []
    for candidate in candidates:
        if candidate.presentation == "neutral":
            spans.append(ArtifactRefStyledSpan(candidate.candidate_span, "neutral"))
            continue
        if candidate.presentation == "unknown":
            spans.append(ArtifactRefStyledSpan(candidate.candidate_span, "unknown"))
            continue
        if candidate.presentation == "malformed":
            spans.append(ArtifactRefStyledSpan(candidate.candidate_span, "error"))
            continue
        spans.extend(
            ArtifactRefStyledSpan(part.span, part.role)
            for part in candidate.parts
            if part.span.end > part.span.start
        )
    return tuple(spans)


def apply_artifact_ref_overlays(
    highlighted: _StylizableText,
    source: str,
    *,
    known_kinds: frozenset[str] | None,
    palette: ArtifactRefStylePalette | None = None,
    region_start: int = 0,
    max_bytes: int,
    max_lines: int,
) -> None:
    """Apply artifact-reference overlays to a Rich ``Text``-like object."""
    try:
        active_palette = palette or artifact_ref_style_palette_from_theme(None)
        candidates = build_artifact_ref_candidate_spans(
            source,
            known_kinds=known_kinds,
            max_bytes=max_bytes,
            max_lines=max_lines,
        )
        for span in artifact_ref_styled_spans(candidates):
            highlighted.stylize(
                active_palette.style_for_key(span.style_key),
                region_start + span.span.start,
                region_start + span.span.end,
            )
    except Exception:
        return


def artifact_ref_candidate_ranges(
    text: str,
    *,
    max_bytes: int,
    max_lines: int,
) -> tuple[ArtifactRefSpan, ...]:
    """Return complete typed-ref candidate ranges for hint suppression."""
    if "@" not in text:
        return ()
    try:
        encoded = text.encode("utf-8")
        if len(encoded) > max_bytes or text.count("\n") > max_lines:
            return ()
        scanner_candidates = scan_artifact_refs(text)
        converted = _candidate_character_spans(text, encoded, scanner_candidates)
    except Exception:
        return ()
    return tuple(spans["candidate"] for spans in converted)


def _candidate_character_spans(
    text: str,
    encoded: bytes,
    candidates: tuple[ArtifactRefPromptCandidate, ...],
) -> tuple[dict[str, ArtifactRefSpan], ...]:
    span_rows = tuple(
        _candidate_byte_spans(encoded, candidate) for candidate in candidates
    )
    if len(encoded) == len(text):
        return span_rows

    offsets = {
        value
        for spans in span_rows
        for span in spans.values()
        for value in (span.start, span.end)
    }
    converted = _byte_to_character_offsets(text, offsets)
    return tuple(
        {
            part: ArtifactRefSpan(
                start=converted[span.start],
                end=converted[span.end],
            )
            for part, span in spans.items()
        }
        for spans in span_rows
    )


def _byte_to_character_offsets(text: str, offsets: set[int]) -> dict[int, int]:
    converted: dict[int, int] = {}
    byte_offset = 0
    for character_offset, character in enumerate(text):
        if byte_offset in offsets:
            converted[byte_offset] = character_offset
        byte_offset += len(character.encode("utf-8"))
    if byte_offset in offsets:
        converted[byte_offset] = len(text)
    if missing := offsets.difference(converted):
        raise ValueError(f"unmapped artifact-ref byte offset(s): {sorted(missing)!r}")
    return converted


def _candidate_byte_spans(
    encoded: bytes,
    candidate: ArtifactRefPromptCandidate,
) -> dict[str, ArtifactRefSpan]:
    spans = {
        "candidate": candidate.candidate_span,
        "sigil": candidate.sigil_span,
        "kind": candidate.kind_span,
        "separator": candidate.separator_span,
        "payload": candidate.payload_span,
    }
    if candidate.fragment_span is not None:
        spans["fragment"] = candidate.fragment_span
    if candidate.quoted:
        open_delimiter = ArtifactRefSpan(
            candidate.separator_span.end,
            candidate.payload_span.start,
        )
        if open_delimiter.end > open_delimiter.start:
            spans["open_delimiter"] = open_delimiter
        close_start = candidate.payload_span.end
        close_end = close_start + 1
        if (
            close_end <= candidate.candidate_span.end
            and encoded[close_start:close_end] == b'"'
        ):
            spans["close_delimiter"] = ArtifactRefSpan(close_start, close_end)
    return spans


def _candidate_parts(
    spans: Mapping[str, ArtifactRefSpan],
) -> Iterator[tuple[ArtifactRefPartRole, ArtifactRefSpan]]:
    for key in (
        "sigil",
        "kind",
        "separator",
        "open_delimiter",
        "payload",
        "close_delimiter",
        "fragment",
    ):
        span = spans.get(key)
        if span is None:
            continue
        role: ArtifactRefPartRole = "delimiter" if key.endswith("_delimiter") else key  # type: ignore[assignment]
        yield role, span


def _presentation(
    candidate: ArtifactRefPromptCandidate,
    known_kinds: frozenset[str] | None,
) -> ArtifactRefPresentation:
    if not candidate.well_formed:
        return "malformed"
    if known_kinds is None:
        return "neutral"
    if candidate.kind not in known_kinds:
        return "unknown"
    return "known"


def _theme_color(theme: Any | None, name: str) -> str:
    value = getattr(theme, name, None) if theme is not None else None
    if isinstance(value, str) and value:
        return value
    return _FALLBACK_THEME[name]


def _style_signature(style: Style) -> str:
    color = _style_color_key(style.color)
    bgcolor = _style_color_key(style.bgcolor)
    flags = "".join(
        name
        for name, enabled in (
            ("b", style.bold),
            ("d", style.dim),
            ("i", style.italic),
            ("u", style.underline),
        )
        if enabled
    )
    return f"{color}/{bgcolor}/{flags}"


def _style_color_key(color: object | None) -> str:
    if color is None:
        return ""
    hex_color = getattr(color, "hex", None)
    return hex_color if isinstance(hex_color, str) else str(color)


__all__ = [
    "ArtifactRefCandidateSpans",
    "ArtifactRefPartSpan",
    "ArtifactRefStylePalette",
    "ArtifactRefStyledSpan",
    "apply_artifact_ref_overlays",
    "artifact_ref_candidate_ranges",
    "artifact_ref_style_palette_from_theme",
    "artifact_ref_styled_spans",
    "build_artifact_ref_candidate_spans",
]
