"""Frozen task-type presentation computed once at gate-creation time.

Two entry points, and only one of them may touch the live catalog:

* :func:`resolve_task_type_gate_display` is the creation-time resolver. It
  reads the task-type registry (and the committed snapshot, through
  :func:`sase.task_type_presentation.task_type_presentation`) and returns a
  persistable :class:`TaskTypeGateDisplay`, or ``None`` for an untyped bead.
* :func:`parse_task_type_gate_display` is the strict, zero-I/O parser that
  validation and later readers use. It never consults the registry.

The four projections — payload, chip, note, and Markdown fact — are pure
functions of an already-resolved record. This module imports nothing from
:mod:`sase.notification_gates`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import re
import unicodedata

from rich.cells import cell_len

from sase.task_type_presentation import format_task_type_chip, task_type_presentation
from sase.task_types._snapshot import task_type_snapshot_entry
from sase.task_types.registry import TaskTypeRegistry, get_task_type_registry

_MAX_FACTS = 3
_MAX_FACT_CELLS = 80
_MAX_GLYPH_CODEPOINTS = 32
_MAX_GLYPH_BYTES = 128
_ELLIPSIS = "…"
_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
_DISPLAY_KEYS = frozenset({"glyph", "name", "accent_color", "facts"})


@dataclass(frozen=True)
class TaskTypeGateDisplay:
    """Persistable glyph, human name, accent, and required-field facts."""

    glyph: str
    name: str
    accent_color: str
    facts: tuple[tuple[str, str], ...]


def resolve_task_type_gate_display(
    task_type: str,
    task_type_fields: Mapping[str, str] | None = None,
    *,
    registry: TaskTypeRegistry | None = None,
) -> TaskTypeGateDisplay | None:
    """Resolve one stored task type into persistable gate presentation.

    Returns ``None`` for an untyped bead. A typed slug always produces a
    record: an unresolved type degrades to the ``?`` glyph, the slug as its
    name, the neutral grey accent, and raw field names as fact labels.

    Pass *registry* to resolve against an already-loaded catalog instead of
    calling :func:`get_task_type_registry` again.
    """
    slug = task_type.strip()
    if not slug:
        return None
    presentation = task_type_presentation(slug, registry=registry)
    fields = task_type_fields or {}
    return TaskTypeGateDisplay(
        glyph=presentation.glyph,
        name=presentation.label,
        accent_color=presentation.accent_color,
        facts=_resolve_facts(slug, fields, registry=registry),
    )


def parse_task_type_gate_display(mapping: object) -> TaskTypeGateDisplay:
    """Parse a stored display mapping, or raise :class:`ValueError`.

    Accepts exactly ``{glyph, name, accent_color, facts}`` and enforces the
    same bounds the resolver produces. Never reads the registry.
    """
    if not isinstance(mapping, Mapping):
        raise ValueError("task type display must be an object")
    extra = set(mapping) - _DISPLAY_KEYS
    missing = _DISPLAY_KEYS - set(mapping)
    if extra or missing:
        raise ValueError(
            "task type display must contain exactly glyph, name, accent_color, facts"
        )
    return TaskTypeGateDisplay(
        glyph=_parse_glyph(mapping.get("glyph")),
        name=_parse_name(mapping.get("name")),
        accent_color=_parse_accent_color(mapping.get("accent_color")),
        facts=_parse_facts(mapping.get("facts")),
    )


def task_type_gate_display_payload(display: TaskTypeGateDisplay) -> dict[str, object]:
    """Return the JSON mapping stored in a gate payload."""
    return {
        "glyph": display.glyph,
        "name": display.name,
        "accent_color": display.accent_color,
        "facts": [[label, value] for label, value in display.facts],
    }


def task_type_gate_chip(display: TaskTypeGateDisplay, slug: str) -> dict[str, str]:
    """Return the ``presentation.chip`` mapping for a frozen display.

    ``label`` is the type slug, matching every other dense bead surface. The
    glyph and label are the same pair :func:`format_task_type_chip` lays out.
    """
    laid_out = format_task_type_chip(display.glyph, slug)
    glyph, separator, label = laid_out.partition(" ")
    if separator != " " or glyph != display.glyph or label != slug:
        raise ValueError("task type chip layout must be '{glyph} {label}'")
    return {
        "glyph": glyph,
        "label": label,
        "color": display.accent_color,
    }


def task_type_gate_note(display: TaskTypeGateDisplay) -> str:
    """Return the compact ``Name · Label: value · Label: value`` note line."""
    parts = [display.name, *(f"{label}: {value}" for label, value in display.facts)]
    return " · ".join(parts)


def task_type_gate_markdown_fact(display: TaskTypeGateDisplay, slug: str) -> str:
    """Return the ``**Task type:** ≈ `flake` `` metadata line."""
    escaped = slug.replace("`", "\\`")
    return f"**Task type:** {format_task_type_chip(display.glyph, f'`{escaped}`')}"


def _resolve_facts(
    slug: str,
    fields: Mapping[str, str],
    *,
    registry: TaskTypeRegistry | None = None,
) -> tuple[tuple[str, str], ...]:
    spec_fields = _spec_fields(slug, registry=registry)
    if spec_fields is None:
        pairs = (
            (_clean_fact_text(name), _clean_fact_value(value))
            for name, value in fields.items()
        )
        return _capped_facts(
            (label, value) for label, value in pairs if label and value
        )
    facts: list[tuple[str, str]] = []
    for field in spec_fields:
        if not isinstance(field, Mapping) or not field.get("required"):
            continue
        name = str(field.get("name") or "").strip()
        if not name:
            continue
        value = _clean_fact_value(fields.get(name))
        if not value:
            continue
        label = str(field.get("label") or name).strip() or name
        facts.append((label, value))
    return _capped_facts(facts)


def _spec_fields(
    slug: str, *, registry: TaskTypeRegistry | None = None
) -> Sequence[object] | None:
    catalog = get_task_type_registry() if registry is None else registry
    record = catalog.by_slug.get(slug)
    if record is not None:
        return _as_field_list(record.spec.get("fields"))
    snapshot = task_type_snapshot_entry(slug)
    if snapshot is None or "fields" not in snapshot:
        return None
    return _as_field_list(snapshot.get("fields"))


def _as_field_list(raw: object) -> Sequence[object]:
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        return raw
    return ()


def _capped_facts(pairs: Iterable[tuple[str, str]]) -> tuple[tuple[str, str], ...]:
    collected: list[tuple[str, str]] = []
    for pair in pairs:
        collected.append(pair)
        if len(collected) == _MAX_FACTS:
            break
    return tuple(collected)


def _clean_fact_value(raw: object) -> str:
    if not isinstance(raw, str):
        return ""
    return _truncate_cells(_clean_fact_text(raw), _MAX_FACT_CELLS)


def _clean_fact_text(raw: str) -> str:
    return " ".join(raw.split())


def _truncate_cells(value: str, max_cells: int) -> str:
    if cell_len(value) <= max_cells:
        return value
    ellipsis_cells = cell_len(_ELLIPSIS)
    if max_cells <= ellipsis_cells:
        return _ELLIPSIS
    limit = max_cells - ellipsis_cells
    out = ""
    for character in value:
        if cell_len(out + character) > limit:
            break
        out += character
    return out + _ELLIPSIS


def _parse_glyph(value: object) -> str:
    if not isinstance(value, str) or not _is_single_glyph(value):
        raise ValueError("glyph must be a single grapheme")
    return value


def _parse_name(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\n" in value
        or _has_control_characters(value)
    ):
        raise ValueError("name must be a non-empty single line")
    return value


def _parse_accent_color(value: object) -> str:
    if not isinstance(value, str) or not _COLOR_RE.fullmatch(value):
        raise ValueError("accent_color must be an '#RRGGBB' hex color")
    return value


def _parse_facts(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("facts must be at most three two-element string pairs")
    if len(value) > _MAX_FACTS:
        raise ValueError("facts must be at most three two-element string pairs")
    parsed: list[tuple[str, str]] = []
    for item in value:
        parsed.append(_parse_fact_pair(item))
    return tuple(parsed)


def _parse_fact_pair(item: object) -> tuple[str, str]:
    if (
        not isinstance(item, Sequence)
        or isinstance(item, (str, bytes))
        or len(item) != 2
    ):
        raise ValueError("facts must be at most three two-element string pairs")
    label, raw_value = item
    if not _is_fact_string(label) or not _is_fact_string(raw_value):
        raise ValueError("facts must be at most three two-element string pairs")
    if cell_len(raw_value) > _MAX_FACT_CELLS:
        raise ValueError("facts must be at most three two-element string pairs")
    return (label, raw_value)


def _is_fact_string(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and "\n" not in value
        and not _has_control_characters(value)
    )


def _is_single_glyph(value: str) -> bool:
    if (
        not value
        or value != value.strip()
        or len(value) > _MAX_GLYPH_CODEPOINTS
        or len(value.encode("utf-8")) > _MAX_GLYPH_BYTES
    ):
        return False
    return _grapheme_cluster_count(value) == 1


def _grapheme_cluster_count(value: str) -> int:
    clusters = 0
    join_next = False
    regional_run = 0
    for character in value:
        codepoint = ord(character)
        if _is_disallowed_glyph_control(character):
            return 2
        if clusters == 0:
            if codepoint == 0x200D or _is_grapheme_extend(character):
                return 2
            clusters = 1
            regional_run = 1 if _is_regional_indicator(codepoint) else 0
            continue
        if join_next:
            if codepoint == 0x200D:
                return 2
            join_next = False
            regional_run = 0
            continue
        if codepoint == 0x200D:
            join_next = True
            regional_run = 0
            continue
        if _is_grapheme_extend(character):
            continue
        if _is_regional_indicator(codepoint) and regional_run % 2 == 1:
            regional_run += 1
            continue
        clusters += 1
        regional_run = 1 if _is_regional_indicator(codepoint) else 0
    return clusters + int(join_next)


def _is_grapheme_extend(character: str) -> bool:
    codepoint = ord(character)
    return (
        unicodedata.combining(character) != 0
        or unicodedata.category(character) in {"Mc", "Me", "Mn"}
        or 0xFE00 <= codepoint <= 0xFE0F
        or 0x1F3FB <= codepoint <= 0x1F3FF
        or 0xE0020 <= codepoint <= 0xE007F
    )


def _is_disallowed_glyph_control(character: str) -> bool:
    codepoint = ord(character)
    return unicodedata.category(character).startswith("C") and not (
        codepoint == 0x200D or 0xE0020 <= codepoint <= 0xE007F
    )


def _is_regional_indicator(codepoint: int) -> bool:
    return 0x1F1E6 <= codepoint <= 0x1F1FF


def _has_control_characters(value: str) -> bool:
    return any(unicodedata.category(character) == "Cc" for character in value)


__all__ = [
    "TaskTypeGateDisplay",
    "parse_task_type_gate_display",
    "resolve_task_type_gate_display",
    "task_type_gate_chip",
    "task_type_gate_display_payload",
    "task_type_gate_markdown_fact",
    "task_type_gate_note",
]
