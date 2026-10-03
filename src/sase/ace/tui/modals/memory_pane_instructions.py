"""Collapsed INSTRUCTIONS rail group and instruction cards (phase instructions-group).

Owns the phase instructions-group Notes rail behind :class:`MemoryPane`
(epic design ``plan:202610/memory_history_tui.md`` §15 and §4.6): a
collapsed ``▸ INSTRUCTIONS · N`` group at the rail's bottom built from
``subjects()`` entries of kind ``instructions``, using the history-only
node kind. ``space`` toggles it.

History presentation comes only through ``sase.pager.history_kit``
(the import-guard door). Stepping, diff, the Timeline lens, and ``H``
all work through the existing selector-keyed machinery: instruction
rows resolve by their repo-relative path exactly like deleted rows do,
and carry their wire subject id so the band renders cause rows, shim
alias chips, and the TEMPLATE chip in the pager's own words.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.console import Group, RenderableType
from rich.text import Text

from sase.ace.tui.memory_panel_catalog import MemoryRailNode
from sase.memory.notes import AGENTS_PARENT, MemoryNote

#: Stable rail identity of the INSTRUCTIONS group header row.
INSTRUCTIONS_GROUP_IDENTITY = "INSTRUCTIONS"

#: Toast refusing edits of SASE-rendered (managed) instruction files.
MANAGED_INSTRUCTION_REFUSAL = "rendered from memory · edit its source notes"

#: Toast for mutation keys on the group header or a row with no subject.
INSTRUCTION_GROUP_TOAST = "INSTRUCTIONS group · select an instruction file first"

#: Toast for hand-written instruction files on destructive keys.
HANDWRITTEN_INSTRUCTION_REFUSAL = "hand-written instruction file · o opens it"

#: Placeholder body while the rendered file loads off-thread.
INSTRUCTION_BODY_LOADING = "_Loading rendered file…_"

#: Card body when the rendered file cannot be read.
INSTRUCTION_BODY_UNAVAILABLE = "_Rendered file unavailable._"


@dataclass(frozen=True)
class InstructionSubject:
    """One ``subjects()`` entry of kind ``instructions`` for the rail."""

    subject_id: str
    path: str
    display: str
    managed: bool
    template: bool
    diverged: bool
    diverged_count: int
    shims: tuple[str, ...]


def _instruction_display_for_subject_id(subject_id: str) -> str:
    """Return the rail name for an instructions wire subject id.

    ``instructions:project:sase/.`` becomes ``AGENTS.md`` and
    ``instructions:project:sase/src/sase/ace`` becomes
    ``src/sase/ace/AGENTS.md`` (mirrors the kit/CLI short display).
    Never raises.
    """
    try:
        _kind, _, rest = str(subject_id or "").partition(":")
        name = rest.split("/", 1)[1] if "/" in rest else rest
        if name in (".", ""):
            return "AGENTS.md"
        return f"{name}/AGENTS.md"
    except Exception:
        return "AGENTS.md"


def _subject_paths(row: dict[str, Any]) -> tuple[str, ...]:
    """Return the wire ``paths`` list, or ``()`` when malformed."""
    try:
        paths = row.get("paths", ())
    except Exception:
        return ()
    if not isinstance(paths, (list, tuple)):
        return ()
    return tuple(str(path) for path in paths if isinstance(path, str) and path)


def instruction_subjects(subjects: Any) -> tuple[InstructionSubject, ...]:
    """Return the kind-``instructions`` entries of a subjects wire dict.

    Rows sort by display path with the workspace root first, so the
    rail order is stable across loads. Never raises: a malformed wire
    yields ``()`` while the rail keeps working.
    """
    try:
        rows = subjects.get("subjects", ()) if isinstance(subjects, dict) else ()
    except Exception:
        return ()
    if not isinstance(rows, (list, tuple)):
        return ()
    found: list[InstructionSubject] = []
    for row in rows:
        try:
            if not isinstance(row, dict) or row.get("kind") != "instructions":
                continue
            subject_id = row.get("id", "")
            if not isinstance(subject_id, str) or not subject_id:
                continue
            paths = _subject_paths(row)
            # The wire ``display_name`` is the bare file name for every
            # row, so the rail names rows by directory from the primary
            # path (``AGENTS.md``, ``src/sase/ace/AGENTS.md``, …).
            primary = paths[0] if paths else ""
            display = primary or _instruction_display_for_subject_id(subject_id)
            try:
                diverged_count = int(row.get("diverged_count", 0) or 0)
            except (TypeError, ValueError):
                diverged_count = 0
            found.append(
                InstructionSubject(
                    subject_id=subject_id,
                    path=primary,
                    display=display,
                    managed=bool(row.get("managed", False)),
                    template=bool(row.get("template", False)),
                    diverged=bool(diverged_count > 0),
                    diverged_count=max(0, diverged_count),
                    shims=tuple(paths[1:] if len(paths) > 1 else ()),
                )
            )
        except Exception:
            continue
    try:
        found.sort(key=lambda subject: (subject.path != "AGENTS.md", subject.path))
    except Exception:
        pass
    return tuple(found)


def is_instruction_subject_row(node: Any) -> bool:
    """Return whether *node* is one instruction file row."""
    try:
        return bool(
            node is not None
            and getattr(node, "history_only", False)
            and not getattr(node, "instruction_group", False)
            and str(getattr(node, "instruction_subject", "") or "")
        )
    except Exception:
        return False


def is_instruction_group_row(node: Any) -> bool:
    """Return whether *node* is the INSTRUCTIONS group header row."""
    try:
        return bool(node is not None and getattr(node, "instruction_group", False))
    except Exception:
        return False


def instruction_node(subject: InstructionSubject) -> MemoryRailNode:
    """Return the history-only rail node for one instruction subject.

    The synthetic note carries the file's repo-relative path so
    history selectors, filters, pins, and pager hand-off resolve
    exactly like a live row; ``instruction_subject`` carries the wire
    id so the band renders the instructions kind. Never raises.
    """
    note = MemoryNote(
        path=Path(subject.path),
        type="reference",
        parent=AGENTS_PARENT,
        description=None,
        body="",
        frontmatter={},
        type_source="missing",
        parent_source="missing",
        source_path=Path(subject.path),
    )
    return MemoryRailNode(
        note=note,
        depth=1,
        history_only=True,
        instruction_subject=subject.subject_id,
    )


def instruction_group_node() -> MemoryRailNode:
    """Return the collapsible INSTRUCTIONS group header row."""
    note = MemoryNote(
        path=Path(INSTRUCTIONS_GROUP_IDENTITY),
        type="reference",
        parent=AGENTS_PARENT,
        description=None,
        body="",
        frontmatter={},
        type_source="missing",
        parent_source="missing",
        source_path=Path(INSTRUCTIONS_GROUP_IDENTITY),
    )
    return MemoryRailNode(
        note=note,
        depth=0,
        history_only=True,
        instruction_group=True,
    )


def build_instructions_group_text(expanded: bool, count: int) -> Text:
    """Return the ``▸ INSTRUCTIONS · N`` group header row. Never raises."""
    try:
        mark = "▾" if expanded else "▸"
        return Text(f"{mark} INSTRUCTIONS · {max(0, int(count))}", style="dim")
    except Exception:
        return Text("▸ INSTRUCTIONS", style="dim")


def _instruction_row_chips(subject: InstructionSubject) -> tuple[str, ...]:
    """Return the dim rail chips for one instruction row, in order."""
    chips: list[str] = []
    try:
        if subject.shims:
            count = len(subject.shims)
            chips.append(f"≡ {count} shim" if count == 1 else f"≡ {count} shims")
    except Exception:
        pass
    try:
        if subject.diverged:
            chips.append("⚠ diverged")
    except Exception:
        pass
    try:
        if subject.template:
            chips.append("TEMPLATE")
    except Exception:
        pass
    return tuple(chips)


def build_instruction_row_text(subject: InstructionSubject) -> Text:
    """Return one instruction rail row: name plus alias/diverged chips."""
    text = Text()
    try:
        text.append("● ")
        text.append(subject.display or subject.path)
        for chip in _instruction_row_chips(subject):
            text.append("  ")
            text.append(chip, style="dim")
    except Exception:
        return Text(subject.display or subject.path or "AGENTS.md")
    return text


def matches_instruction_filter(subject: InstructionSubject, pattern: str) -> bool:
    """Return whether *subject* matches the rail filter (by path)."""
    try:
        needle = str(pattern or "").strip().casefold()
    except Exception:
        return True
    if not needle:
        return True
    try:
        if needle in "instructions":
            return True
        return needle in str(subject.path or "").casefold()
    except Exception:
        return True


def build_instruction_card_title(
    display: str,
    path_label: str,
    *,
    scope_display_name: str,
    accent: str,
) -> RenderableType:
    """Build the instruction card title in the rail badge grammar."""
    identity = Text()
    identity.append("I", style=f"bold {accent}")
    identity.append(" ")
    identity.append("INSTRUCTIONS", style=f"bold {accent}")
    identity.append("  ")
    identity.append(display, style="bold")
    if scope_display_name:
        from rich.table import Table

        first_line = Table.grid(expand=True, padding=(0, 0, 0, 2))
        first_line.add_column(ratio=1, overflow="ellipsis")
        first_line.add_column(justify="right", no_wrap=True)
        first_line.add_row(identity, Text(scope_display_name, style=f"bold {accent}"))
        lines: list[RenderableType] = [first_line]
    else:
        lines = [identity]
    lines.append(Text(path_label, style="dim"))
    return Group(*lines)


def build_instruction_group_card_title(
    count: int, *, scope_display_name: str, accent: str
) -> RenderableType:
    """Build the group header card title (``I INSTRUCTIONS · N``)."""
    return build_instruction_card_title(
        f"{max(0, int(count))} files",
        "space expands · collapses",
        scope_display_name=scope_display_name,
        accent=accent,
    )


def build_instruction_card_meta(
    subject: InstructionSubject, *, accent: str
) -> RenderableType:
    """Build the instruction meta grid: source kind plus shims."""
    from .memory_panel_rendering import append_badge, build_property_grid

    sections: list[RenderableType] = []
    badges = Text()
    try:
        append_badge(
            badges,
            "MANAGED · RENDERED FROM MEMORY" if subject.managed else "HAND-WRITTEN",
            accent=accent,
        )
        if subject.template:
            append_badge(badges, "TEMPLATE", accent=accent)
        if subject.diverged:
            append_badge(badges, "⚠ DIVERGED", accent=accent)
    except Exception:
        badges = Text()
    if badges.plain:
        sections.append(badges)
    rows: list[tuple[str, str | RenderableType]] = [
        (
            "Source",
            "rendered from memory notes"
            if subject.managed
            else "hand-written file on disk",
        ),
    ]
    try:
        if subject.shims:
            rows.append(("Shims", " · ".join(subject.shims)))
    except Exception:
        pass
    try:
        if subject.diverged:
            rows.append(
                (
                    "Diverged",
                    f"{subject.diverged_count} versions differ across shims",
                )
            )
    except Exception:
        pass
    try:
        sections.append(build_property_grid(rows, accent=accent))
    except Exception:
        pass
    if not sections:
        return Text("", style="dim")
    if len(sections) == 1:
        return sections[0]
    return Group(*sections)


def instruction_edit_refusal(subject: InstructionSubject | None) -> str:
    """Return the edit toast for an instruction row (managed vs hand-written)."""
    try:
        if subject is not None and not subject.managed:
            return HANDWRITTEN_INSTRUCTION_REFUSAL
    except Exception:
        pass
    return MANAGED_INSTRUCTION_REFUSAL


__all__ = [
    "HANDWRITTEN_INSTRUCTION_REFUSAL",
    "INSTRUCTIONS_GROUP_IDENTITY",
    "INSTRUCTION_BODY_LOADING",
    "INSTRUCTION_BODY_UNAVAILABLE",
    "INSTRUCTION_GROUP_TOAST",
    "InstructionSubject",
    "MANAGED_INSTRUCTION_REFUSAL",
    "build_instruction_card_meta",
    "build_instruction_card_title",
    "build_instruction_group_card_title",
    "build_instruction_row_text",
    "build_instructions_group_text",
    "instruction_edit_refusal",
    "instruction_group_node",
    "instruction_node",
    "instruction_subjects",
    "is_instruction_group_row",
    "is_instruction_subject_row",
    "matches_instruction_filter",
]
